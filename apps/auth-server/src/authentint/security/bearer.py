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


async def verify_access_token(session: AsyncSession, token: str) -> dict:
    try:
        tok = jwt.decode(token, KeySet.import_key_set(await keystore.jwks(session)), algorithms=["RS256"])
        jwt.JWTClaimsRegistry(
            iss={"essential": True, "value": settings.issuer},
            exp={"essential": True},
        ).validate(tok.claims)
    except JoseError:
        raise HTTPException(401, "invalid_token")
    return tok.claims

def require_scope(scope: str):
    """
    Route protection using scopes
    """
    async def dep(cred: HTTPAuthorizationCredentials = Depends(bearer), session=Depends(get_session)) -> dict:
        claims = await verify_access_token(session, cred.credentials)

        if scope not in claims["scope"].split():
            raise HTTPException(403, "insufficient_scope")

        return claims

    return dep
