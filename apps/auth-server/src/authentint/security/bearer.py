from fastapi.security import HTTPBearer
from fastapi.security import HTTPAuthorizationCredentials
from joserfc import jwt
from joserfc.jwk import KeySet
from joserfc.errors import JoseError
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import HTTPException
from fastapi import Depends

from authentint.keys import keystore
from authentint.config import settings
from authentint.infra.database import get_session


bearer = HTTPBearer()


async def verify_access_token(session: AsyncSession, token: str, audience: str | None = None) -> dict:
    """
    Signature (RS256 pinned), typ, iss, exp; and `aud` must contain `audience` when given (ADR §11):
    a token minted for svc-impots alone must not open /userinfo.
    """

    try:
        tok = jwt.decode(token, KeySet.import_key_set(await keystore.jwks(session)), algorithms=["RS256"])
        if tok.header.get("typ") != "at+jwt":
            raise HTTPException(401, "invalid_token")
        jwt.JWTClaimsRegistry(
            iss={"essential": True, "value": settings.issuer},
            exp={"essential": True},
        ).validate(tok.claims)
    except JoseError:
        raise HTTPException(401, "invalid_token")

    aud = tok.claims.get("aud")
    if audience is not None and audience not in (aud if isinstance(aud, list) else [aud]):
        raise HTTPException(401, "invalid_token")

    return tok.claims

def require_scope(scope: str):
    """
    Route protection using scopes
    """
    async def dep(cred: HTTPAuthorizationCredentials = Depends(bearer), session=Depends(get_session)) -> dict:
        claims = await verify_access_token(session, cred.credentials)

        if scope not in claims.get("scope", "").split():
            raise HTTPException(403, "insufficient_scope")

        return claims

    return dep

def require_audience(audience: str):
    """Route protection for the auth-server's own APIs (/me...): the token must name `audience`."""

    async def dep(cred: HTTPAuthorizationCredentials = Depends(bearer), session=Depends(get_session)) -> dict:
        return await verify_access_token(session, cred.credentials, audience)

    return dep
