from fastapi.security import HTTPBearer
from fastapi.security import HTTPAuthorizationCredentials
from joserfc import jwt
from joserfc.jwk import KeySet
from joserfc.errors import JoseError
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import HTTPException
from fastapi import Depends
from uuid import UUID

from authentint.keys import keystore
from authentint.config import settings
from authentint.infra.database import get_session
from authentint.domain.scopes import IDP_AUDIENCE
from authentint.infra.models.identity import User
from authentint.infra.models.identity import UserStatus


bearer = HTTPBearer()


def bearer_error(status: int, error: str) -> HTTPException:
    """RFC 6750 §3: a Bearer failure says why in WWW-Authenticate, for the client to tell "refresh" from "re-consent"."""

    return HTTPException(status, error, headers={"WWW-Authenticate": f'Bearer error="{error}"'})

async def verify_access_token(session: AsyncSession, token: str, audience: str | None = None) -> dict:
    """
    Signature (RS256 pinned), typ, iss, exp; and `aud` must contain `audience` when given (ADR §11):
    a token minted for svc-impots alone must not open /userinfo.
    """

    try:
        tok = jwt.decode(token, KeySet.import_key_set(await keystore.jwks(session)), algorithms=["RS256"])
        if tok.header.get("typ") != "at+jwt":
            raise bearer_error(401, "invalid_token")
        jwt.JWTClaimsRegistry(
            iss={"essential": True, "value": settings.issuer},
            exp={"essential": True},
        ).validate(tok.claims)
    except JoseError:
        raise bearer_error(401, "invalid_token")

    aud = tok.claims.get("aud")
    if audience is not None and audience not in (aud if isinstance(aud, list) else [aud]):
        raise bearer_error(401, "invalid_token")

    return tok.claims

def require_scope(scope: str):
    """
    Route protection using scopes
    """
    async def dep(cred: HTTPAuthorizationCredentials = Depends(bearer), session=Depends(get_session)) -> dict:
        claims = await verify_access_token(session, cred.credentials)

        if scope not in claims.get("scope", "").split():
            raise bearer_error(403, "insufficient_scope")

        return claims

    return dep

def require_audience(audience: str):
    """Route protection for the auth-server's own APIs (/me...): the token must name `audience`."""

    async def dep(cred: HTTPAuthorizationCredentials = Depends(bearer), session=Depends(get_session)) -> dict:
        return await verify_access_token(session, cred.credentials, audience)

    return dep

# One instance, so FastAPI verifies the token once per request even when several dependencies need it
idp_claims = require_audience(IDP_AUDIENCE)

async def current_user(claims: dict = Depends(idp_claims), session=Depends(get_session)) -> User:
    """The /me* user: `sub` of a token naming the IdP. A token outlives a disabled account by up to 10 min: not here."""

    user = await session.get(User, UUID(claims["sub"]))

    if user is None or user.status != UserStatus.active:
        raise bearer_error(401, "invalid_token")

    return user
