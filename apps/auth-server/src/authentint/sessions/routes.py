"""
/me/sessions (ADR §9: "plusieurs appareils") and /admin/sessions — B4.

A user sees and closes their own devices only: someone else's session answers 404, exactly
like an unknown one, so ids can't be probed (IDOR). Closing a session also revokes the refresh
tokens issued under it (oidc/refresh.revoke_session): nothing it produced outlives it.
"""

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter
from fastapi import Depends
from fastapi import HTTPException
from fastapi import Query
from fastapi import Response
from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import IPvAnyAddress
from sqlalchemy import func
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from authentint.audit import audit
from authentint.infra.database import get_session
from authentint.infra.models.audit import Sessions
from authentint.infra.models.identity import User
from authentint.oidc import refresh
from authentint.security.bearer import current_user
from authentint.security.bearer import idp_claims
from authentint.security.bearer import require_scope
from authentint.sessions import queries as sessions


router = APIRouter()

admin_users = require_scope("svc:admin.users")


class SessionView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    device_label: str
    ip_address: IPvAnyAddress
    created_at: datetime
    last_seen_at: datetime | None
    expires_at: datetime

class MySession(SessionView):
    current: bool  # the device this token was issued to (its `sid`)

class AdminSession(SessionView):
    user_id: UUID
    revoked_at: datetime | None
    revocation_reason: str | None

class SessionPage(BaseModel):
    items: list[AdminSession]
    total: int


def is_live():
    return Sessions.revoked_at.is_(None), Sessions.expires_at > func.now()


@router.get("/me/sessions", response_model=list[MySession], tags=["me"])
async def my_sessions(claims: dict = Depends(idp_claims), user: User = Depends(current_user),
                      session: AsyncSession = Depends(get_session)):
    rows = await session.scalars(select(Sessions).where(Sessions.user_id == user.id, *is_live()).order_by(Sessions.created_at.desc()))
    sid = UUID(claims["sid"])

    return [MySession(**SessionView.model_validate(row).model_dump(), current=row.id == sid) for row in rows]

@router.delete("/me/sessions/{session_id}", status_code=204, tags=["me"], responses={404: {"description": "Unknown, closed, or someone else's"}})
async def close_my_session(session_id: UUID, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    sso = await sessions.live(session, session_id)

    if sso is None or sso.user_id != user.id:
        raise HTTPException(404, "unknown_session")  # same answer: whether the id exists is not told

    await refresh.revoke_session(session, sso.id, "revoked_by_user")
    await audit.emit(session, "session.revoked", actor=user.id, outcome="success", detail={}, session_id=sso.id)
    await session.commit()

    return Response(status_code=204)


@router.get("/admin/sessions", response_model=SessionPage, tags=["admin"])
async def list_sessions(user_id: UUID | None = None, include_closed: bool = Query(False, description="Revoked and expired too"),
                        limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0),
                        claims: dict = Depends(admin_users), session: AsyncSession = Depends(get_session)):
    query = select(Sessions)
    if user_id is not None:
        query = query.where(Sessions.user_id == user_id)
    if not include_closed:
        query = query.where(*is_live())

    total = await session.scalar(select(func.count()).select_from(query.subquery()))
    items = await session.scalars(query.order_by(Sessions.created_at.desc(), Sessions.id).limit(limit).offset(offset))

    return SessionPage(items=items.all(), total=total)

@router.delete("/admin/sessions/{session_id}", status_code=204, tags=["admin"], responses={404: {"description": "Unknown or already closed"}})
async def close_session(session_id: UUID, claims: dict = Depends(admin_users), session: AsyncSession = Depends(get_session)):
    sso = await sessions.live(session, session_id)

    if sso is None:
        raise HTTPException(404, "unknown_session")

    await refresh.revoke_session(session, sso.id, "revoked_by_admin")
    await audit.emit(session, "admin.session.revoked", actor=UUID(claims["sub"]), outcome="success",
                     detail={"target_session_id": str(sso.id), "target_user_id": str(sso.user_id)}, session_id=sso.id)
    await session.commit()

    return Response(status_code=204)
