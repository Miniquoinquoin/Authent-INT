"""
/userinfo (OIDC Core §5.3): who the access token's user is, for the client that holds it.

Only a token naming the IdP in `aud` (granted openid) gets in. The numero fiscal is never part
of the answer (ADR §7): it is a login identifier, not a claim.
"""

from uuid import UUID

from fastapi import Depends
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from fastapi.security import HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from . import router
from authentint.domain.scopes import IDP_AUDIENCE
from authentint.infra.database import get_session
from authentint.infra.models.identity import User
from authentint.infra.models.identity import UserStatus
from authentint.security.bearer import bearer_error
from authentint.security.bearer import verify_access_token


@router.get("/userinfo")
@router.post("/userinfo")
async def userinfo(cred: HTTPAuthorizationCredentials | None = Depends(HTTPBearer(auto_error=False)),
                   session: AsyncSession = Depends(get_session)):
    if cred is None:
        # RFC 6750 §3.1: no credentials at all is not an error code, just the challenge
        raise HTTPException(401, "unauthorized", headers={"WWW-Authenticate": "Bearer"})

    claims = await verify_access_token(session, cred.credentials, audience=IDP_AUDIENCE)
    scopes = claims.get("scope", "").split()

    if "openid" not in scopes:
        raise bearer_error(403, "insufficient_scope")

    user = await session.get(User, UUID(claims["sub"]))

    # a token outlives a disabled account by up to 10 min; /userinfo at least doesn't vouch for it
    if user is None or user.status != UserStatus.active:
        raise bearer_error(401, "invalid_token")

    info = {"sub": str(user.id), "name": f"{user.prenom} {user.nom}", "given_name": user.prenom,
            "family_name": user.nom, "role": user.role.value}

    if "email" in scopes:
        info["email"] = user.email

    return info
