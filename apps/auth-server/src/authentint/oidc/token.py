import base64
import hashlib
import secrets
import time

from datetime import timedelta

from pydantic import BaseModel
from pydantic import Field
from typing import Literal
from typing import Annotated
from urllib.parse import unquote
from joserfc.jwk import RSAKey
from joserfc import jwt
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi.security import HTTPBasicCredentials
from fastapi import Depends
from fastapi import Form
from fastapi import Request
from fastapi.security import HTTPBasic
from fastapi.responses import JSONResponse

from . import router
from authentint.config import settings
from authentint.infra.database import get_session
from authentint.infra.models.audit import Sessions
from authentint.infra.models.oauth import OAuthClients
from authentint.infra.models.oauth import ClientType
from authentint.infra.models.identity import User
from authentint.infra.models.identity import UserStatus
from authentint.domain.errors import OAuthError
from authentint.domain.claims import IdToken
from authentint.domain.claims import RefreshedIdToken
from authentint.domain.claims import AccessToken
from authentint.domain.scopes import audiences
from authentint.clients import queries as clients
from authentint.sessions import queries as sessions
from authentint.security.passwords import verify_password
from authentint.oidc.codes import consume_code
from authentint.oidc import refresh
from authentint.keys import keystore
from authentint.security import ratelimit
from authentint.ops.metrics import TOKEN_GRANTS


TOKEN_LIMIT = 30                      # /token calls per IP...
TOKEN_WINDOW = timedelta(minutes=1)   # ...per minute: a browser refreshes every 10 min, a script guessing secrets/codes far more


class TokenBody(BaseModel):
    grant_type: Literal["authorization_code"]
    code: str
    redirect_uri: str
    client_id: str
    code_verifier: str = Field(min_length=43, max_length=128)

class RefreshBody(BaseModel):
    grant_type: Literal["refresh_token"]
    refresh_token: str = Field(min_length=1, max_length=512)
    client_id: str
    scope: str | None = Field(None, max_length=1024)  # RFC 6749 §6: may narrow, never widen


async def authenticate_client(session: AsyncSession, client_id: str, credentials: HTTPBasicCredentials | None, grant_type: str | None = None) -> OAuthClients:
    """RFC 6749 §2.3.1. `grant_type` is checked against the client's allowed grants when given (/token, not /revoke)."""

    # RFC 6749 §2.3.1: Basic id/secret are URL-encoded; must match the body's client_id
    if credentials is not None and unquote(credentials.username) != client_id:
        raise OAuthError("invalid_client")

    client = await clients.get(session, client_id)
    if client is None:
        raise OAuthError("invalid_client")

    # public clients have no secret; PKCE in consume_code is their proof
    if client.type == ClientType.public and credentials is not None:
        raise OAuthError("invalid_client")

    if client.type == ClientType.confidential and (
        credentials is None
        or not client.secret_hash
        or not await verify_password(client.secret_hash, unquote(credentials.password))
    ):
        raise OAuthError("invalid_client")

    if grant_type is not None and grant_type not in client.allowed_grants:
        raise OAuthError("unauthorized_client")

    return client

def sign(claims: dict, key: RSAKey, typ: str = "JWT") -> str:
    header = {"alg": "RS256", "typ": typ, "kid": key.kid}

    return jwt.encode(header, claims, key) # header.payload.signature

def at_hash(access_token: str) -> str:
    """OIDC Core §3.1.3.6: base64url, unpadded, of the left half of SHA-256 (RS256's hash) of the access token's ASCII."""

    digest = hashlib.sha256(access_token.encode("ascii")).digest()

    return base64.urlsafe_b64encode(digest[:len(digest) // 2]).rstrip(b"=").decode()

def id_claims(user: User, sso: Sessions, client_id: str, now: int, access_token: str, nonce: str | None) -> dict:
    """
    Builds the ID token's content to be addressed to the client app (portail-web).
    nonce=None only on refresh (OIDC Core §12.2), which then builds the nonce-less RefreshedIdToken.
    """

    claims = dict(
        iss=settings.issuer,
        sub=user.id,
        aud=client_id,
        exp=now + settings.id_token_ttl,
        iat=now,
        auth_time=int(sso.created_at.timestamp()),  # the original login, also after a refresh
        acr=sso.acr,
        amr=sso.amr,
        sid=sso.id,
        name=f"{user.prenom} {user.nom}",
        given_name=user.prenom,
        family_name=user.nom,
        role=user.role,
        at_hash=at_hash(access_token)
    )
    id_token = RefreshedIdToken(**claims) if nonce is None else IdToken(nonce=nonce, **claims)

    return id_token.model_dump(mode="json")

def access_claims(user: User, sso: Sessions, client_id: str, scope: str, now: int) -> dict:
    access_token = AccessToken(
        iss=settings.issuer,
        sub=user.id,
        aud=audiences(set(scope.split())),
        client_id=client_id,
        scope=scope,
        exp=now + settings.access_token_ttl,
        iat=now,
        jti=secrets.token_urlsafe(16),
        sid=sso.id,
        acr=sso.acr
    )

    return access_token.model_dump(mode="json")

async def holder(session: AsyncSession, origin) -> tuple[User, Sessions]:
    """The user and session behind a code or refresh token: both must still be alive, or nothing is issued."""

    sso = await sessions.live(session, origin.session_id)
    user = await session.get(User, origin.user_id)

    if sso is None or user is None or user.status != UserStatus.active:
        raise OAuthError("invalid_grant")

    return user, sso

async def tokens(session: AsyncSession, user: User, sso: Sessions, client_id: str, scope: str, nonce: str | None) -> dict:
    key = await keystore.active(session)
    now = int(time.time()) # using linux time representation (seconds ellapsed from...)
    access_token: str = sign(access_claims(user, sso, client_id, scope, now), key, typ="at+jwt")

    body: dict = {
        "access_token": access_token,
        "token_type": "Bearer",
        "expires_in": settings.access_token_ttl,
        "scope": scope
    }

    if "openid" in scope.split():  # a refresh may narrow openid away: then no identity to assert
        body["id_token"] = sign(id_claims(user, sso, client_id, now, access_token, nonce), key)

    return body

async def code_tokens(session: AsyncSession, client: OAuthClients, body: TokenBody) -> dict:
    code = await consume_code(session, body.code, client.id, body.redirect_uri, body.code_verifier)
    user, sso = await holder(session, code)
    response = await tokens(session, user, sso, client.id, code.scope, code.nonce)

    if "offline_access" in code.scope.split():
        response["refresh_token"] = await refresh.issue_refresh(session, code)

    return response

async def refresh_tokens(session: AsyncSession, client: OAuthClients, body: RefreshBody) -> dict:
    """RFC 6749 §6 with rotation and replay detection (ADR §10)."""

    row = await refresh.find(session, body.refresh_token)

    if row is None or row.client_id != client.id:
        raise OAuthError("invalid_grant")

    if row.rotated_at is not None or row.revoked_at is not None:
        await refresh.replayed(session, row)
        raise OAuthError("invalid_grant")

    if refresh.is_expired(row):
        raise OAuthError("invalid_grant")

    scope = " ".join(sorted(set(body.scope.split()))) if body.scope else row.scope
    if not set(scope.split()) <= set(row.scope.split()):
        raise OAuthError("invalid_scope")

    user, sso = await holder(session, row)

    # Checked last, right before issuing: losing this race means another request used the token first
    if not await refresh.rotate(session, row):
        await refresh.replayed(session, row)
        raise OAuthError("invalid_grant")

    response = await tokens(session, user, sso, client.id, scope, nonce=None)
    response["refresh_token"] = await refresh.issue_refresh(session, row)  # commits the rotation with it

    return response

@router.post("/token", responses={429: {"description": "Rate limited (per IP)"}})
async def issue_tokens(body: Annotated[TokenBody | RefreshBody, Form()], request: Request, credentials: HTTPBasicCredentials | None = Depends(HTTPBasic(auto_error=False)), session: AsyncSession = Depends(get_session)):
    # Before any Argon2 (client secret) work. Committed now: a 400 below must still count.
    ip = request.client.host if request.client else "unknown"
    ok = await ratelimit.hit(session, f"token:ip:{ip}", TOKEN_LIMIT, TOKEN_WINDOW)
    await session.commit()
    if not ok:
        TOKEN_GRANTS.labels(body.grant_type, "failure").inc()
        # RFC 6749 §5.2 has no error code for "too many requests", and a 400 would tell the client
        # its request is wrong. HTTP has the answer: 429 + Retry-After (RFC 6585 §4). The body reuses
        # the registered OAuth value closest in meaning, temporarily_unavailable (RFC 6749 §4.1.2.1).
        return JSONResponse({"error": "temporarily_unavailable"}, status_code=429,
                            headers={"Cache-Control": "no-store", "Retry-After": str(int(TOKEN_WINDOW.total_seconds()))})

    try:
        client = await authenticate_client(session, body.client_id, credentials, body.grant_type)

        if isinstance(body, TokenBody):
            response = await code_tokens(session, client, body)
        else:
            response = await refresh_tokens(session, client, body)
    except OAuthError:
        TOKEN_GRANTS.labels(body.grant_type, "failure").inc()
        raise
    TOKEN_GRANTS.labels(body.grant_type, "success").inc()

    return JSONResponse(response, headers={"Cache-Control": "no-store"})
