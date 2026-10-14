"""
/revoke (RFC 7009): a client gives up a refresh token, e.g. on logout.

Access tokens are stateless JWTs: nothing to revoke here, they die at `exp` (10 min). The answer is
still 200, as for an unknown token (§2.2): the client can do nothing more about either.
"""

from typing import Annotated

from fastapi import Depends
from fastapi import Form
from fastapi import Response
from fastapi.security import HTTPBasic
from fastapi.security import HTTPBasicCredentials
from pydantic import BaseModel
from pydantic import Field
from sqlalchemy.ext.asyncio import AsyncSession

from . import router
from authentint.audit import audit
from authentint.domain.errors import OAuthError
from authentint.infra.database import get_session
from authentint.oidc import refresh
from authentint.oidc.token import authenticate_client


class RevokeBody(BaseModel):
    token: str = Field(min_length=1, max_length=4096)
    token_type_hint: str | None = None  # §2.1: optional; we look the token up whatever it says
    client_id: str


@router.post("/revoke", status_code=200)
async def revoke(body: Annotated[RevokeBody, Form()], credentials: HTTPBasicCredentials | None = Depends(HTTPBasic(auto_error=False)),
                 session: AsyncSession = Depends(get_session)):
    client = await authenticate_client(session, body.client_id, credentials)  # no grant check: any client may give up its tokens
    row = await refresh.find(session, body.token)

    if row is not None:
        # §2.1: "verifies whether the token was issued to the client making the revocation request. If this
        # validation fails, the request is refused" with a §5.2 RFC 6749 error: invalid_grant is the one for
        # a refresh token "issued to another client". The other client's token is left untouched.
        if row.client_id != client.id:
            raise OAuthError("invalid_grant")

        await refresh.revoke_family(session, row.family_id, "revoked_by_client")
        await audit.emit(session, "token.revoked", actor=row.user_id, outcome="success", detail={},
                         client_id=client.id, session_id=row.session_id)
        await session.commit()

    return Response(status_code=200, headers={"Cache-Control": "no-store"})
