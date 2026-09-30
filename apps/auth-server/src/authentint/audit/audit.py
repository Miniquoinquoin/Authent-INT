from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID
from datetime import datetime
from datetime import UTC

from authentint.infra.models.audit import AuditEvents
from authentint.audit.middleware import client_ip_var
from authentint.audit.middleware import request_id_var


FORBIDDEN = {"password", "numero_fiscal", "token", "code", "secret"}


async def emit(session: AsyncSession, event_type: str, *, actor: UUID | None, outcome: str, detail: dict):
    assert not FORBIDDEN & detail.keys(), "auditing  with a secret in plain text"

    session.add(AuditEvents(
        occurred_at=datetime.now(UTC),
        event_type=event_type,
        actor_user_id=actor,
        actor_ip=client_ip_var.get(),
        outcome=outcome,
        detail=detail,
        request_id=request_id_var.get()
    ))
