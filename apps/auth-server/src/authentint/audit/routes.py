"""
/me/audit (one's own history) and /admin/audit (filter, page, export; ADR §9) — B4.

Read-only by construction: the runtime role can't UPDATE or DELETE audit_events (migration
3c1e7a2b9d04). Pages go by id cursor (`before`), newest first: stable while new events arrive,
unlike an offset. `detail` is returned as is: audit.emit refuses secrets in it.
"""

import csv
import io
import json

from datetime import datetime
from typing import Any
from typing import Literal
from uuid import UUID

from fastapi import APIRouter
from fastapi import Depends
from fastapi import Query
from fastapi import Response
from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import IPvAnyAddress
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from authentint.infra.database import get_session
from authentint.infra.models.audit import AuditEvents
from authentint.infra.models.audit import Outcome
from authentint.infra.models.identity import User
from authentint.security.bearer import current_user
from authentint.security.bearer import require_scope


router = APIRouter()

admin_audit = require_scope("svc:admin.audit")

CSV_CAP = 10_000  # rows per export: narrow the filters (since/until) or page with `before` for more
CSV_COLUMNS = ["id", "occurred_at", "event_type", "outcome", "actor_user_id", "actor_ip", "client_id", "session_id", "request_id", "detail"]


class AuditEventView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    occurred_at: datetime
    event_type: str
    outcome: Outcome
    actor_user_id: UUID | None
    actor_ip: IPvAnyAddress
    client_id: str | None
    session_id: UUID | None
    detail: dict[str, Any]

class AuditPage(BaseModel):
    items: list[AuditEventView]
    next_before: int | None  # pass as `before` for the next (older) page; null: no more


async def page(session: AsyncSession, query, limit: int, before: int | None) -> AuditPage:
    if before is not None:
        query = query.where(AuditEvents.id < before)
    rows = (await session.scalars(query.order_by(AuditEvents.id.desc()).limit(limit + 1))).all()  # one more: is there a next page?

    return AuditPage(items=rows[:limit], next_before=rows[limit - 1].id if len(rows) > limit else None)

def cell(value) -> str:
    """OWASP CSV injection: request_id comes from a request header, and a spreadsheet runs "=..." as a formula."""

    text = "" if value is None else str(value)
    return "'" + text if text[:1] in ("=", "+", "-", "@", "\t", "\r") else text

def as_csv(rows) -> Response:
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(CSV_COLUMNS)
    for row in rows:
        writer.writerow([cell(v) for v in (row.id, row.occurred_at.isoformat(), row.event_type, row.outcome.value, row.actor_user_id,
                                           row.actor_ip, row.client_id, row.session_id, row.request_id, json.dumps(row.detail))])

    return Response(out.getvalue(), media_type="text/csv",
                    headers={"Content-Disposition": 'attachment; filename="audit.csv"', "Cache-Control": "no-store"})


@router.get("/me/audit", response_model=AuditPage, tags=["me"])
async def my_audit(limit: int = Query(50, ge=1, le=100), before: int | None = Query(None, ge=1),
                   user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    """The user's own events (logins, password changes, closed sessions...), newest first."""

    return await page(session, select(AuditEvents).where(AuditEvents.actor_user_id == user.id), limit, before)

@router.get("/admin/audit", response_model=AuditPage, tags=["admin"], responses={
    200: {"content": {"text/csv": {}}, "description": f"JSON page, or with format=csv every matching row up to {CSV_CAP}"},
})
async def search_audit(event_type: str | None = Query(None, max_length=100), actor_user_id: UUID | None = None,
                       outcome: Outcome | None = None, client_id: str | None = Query(None, max_length=100),
                       since: datetime | None = None, until: datetime | None = None,
                       limit: int = Query(50, ge=1, le=100), before: int | None = Query(None, ge=1),
                       format: Literal["json", "csv"] = "json",
                       claims: dict = Depends(admin_audit), session: AsyncSession = Depends(get_session)):
    query = select(AuditEvents)
    if event_type is not None:
        query = query.where(AuditEvents.event_type == event_type)
    if actor_user_id is not None:
        query = query.where(AuditEvents.actor_user_id == actor_user_id)
    if outcome is not None:
        query = query.where(AuditEvents.outcome == outcome)
    if client_id is not None:
        query = query.where(AuditEvents.client_id == client_id)
    if since is not None:
        query = query.where(AuditEvents.occurred_at >= since)  # on the partition key: only the months asked are read
    if until is not None:
        query = query.where(AuditEvents.occurred_at < until)

    if format == "csv":
        if before is not None:
            query = query.where(AuditEvents.id < before)
        return as_csv(await session.scalars(query.order_by(AuditEvents.id.desc()).limit(CSV_CAP)))

    return await page(session, query, limit, before)
