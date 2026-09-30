import secrets

from pydantic import BaseModel
from pydantic import Field
from typing import Literal
from urllib.parse import unquote
from joserfc.jwk import RSAKey
from joserfc import jwt
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi.security import HTTPBasicCredentials

from authentint.config import settings
from authentint.infra.models.oauth import OAuthClients
from authentint.infra.models.oauth import OAuthAuthorizationCodes
from authentint.infra.models.oauth import ClientType
from authentint.infra.models.identity import User
from authentint.domain.errors import OAuthError
from authentint.domain.claims import IdToken
from authentint.domain.claims import AccessToken
from authentint.clients import queries as clients
from authentint.security.passwords import verify_password
from authentint.domain.scopes import audiences


class TokenBody(BaseModel):
    grant_type: Literal["authorization_code"]
    code: str
    redirect_uri: str
    client_id: str
    code_verifier: str = Field(min_length=43, max_length=128)


async def authenticate_client(session: AsyncSession, client_id: str, credentials: HTTPBasicCredentials | None) -> OAuthClients:
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

    if "authorization_code" not in client.allowed_grants:
        raise OAuthError("unauthorized_client")

    return client

def sign(claims: dict, key: RSAKey, typ: str = "JWT") -> str:
    header = {"alg": "RS256", "typ": typ, "kid": key.kid}

    return jwt.encode(header, claims, key) # header.payload.signature

def id_claims(row: OAuthAuthorizationCodes, user: User, now: int) -> dict:
    """
    Builds the ID token's content to be addressed to the client app (portail-web)
    """

    id_token = IdToken(
        iss=settings.issuer,
        sub=row.user_id,
        aud=row.client_id,
        exp=now + settings.id_token_ttl,
        iat=now,
        auth_time=int(row.auth_time.timestamp()),
        nonce=row.nonce,
        acr=row.acr,
        amr=row.amr,
        sid=row.session_id,
        name=f"{user.prenom} {user.nom}",
        given_name=user.prenom,
        family_name=user.nom,
        role=user.role
    )

    return id_token.model_dump(mode="json")

def access_claims(row: OAuthAuthorizationCodes, now: int) -> dict:
    access_token = AccessToken(
        iss=settings.issuer,
        sub=row.user_id,
        aud=audiences(set(row.scope.split())),
        client_id=row.client_id,
        scope=row.scope,
        exp=now + settings.access_token_ttl,
        iat=now,
        jti=secrets.token_urlsafe(16),
        sid=row.session_id,
        acr=row.acr
    )

    return access_token.model_dump(mode="json")

async def issue_refresh(session: AsyncSession, row) -> str:
    pass
