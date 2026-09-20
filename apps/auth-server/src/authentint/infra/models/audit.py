import uuid
import enum
from sqlalchemy import String
from sqlalchemy import BigInteger
from sqlalchemy.orm import Mapped, mapped_column
from authentint.infra.database import Base
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy import Enum
from datetime import datetime
from typing import Any
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import INET
from sqlalchemy import DateTime
from sqlalchemy import func
from sqlalchemy import ForeignKey


class Outcome(str, enum.Enum):
    success = "success"
    failure = "failure"

class Sessions(Base):
    __tablename__ = "sessions"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    device_label: Mapped[str]
    user_agent: Mapped[str]
    ip_address: Mapped[str] = mapped_column(INET)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revocation_reason: Mapped[str | None]
    acr: Mapped[str]
    amr: Mapped[list[str]] = mapped_column(ARRAY(String))

class AuditEvents(Base):
    __tablename__ = "audit_events"
    __table_args__ = {"postgresql_partition_by": "RANGE (occurred_at)"}
    # Postgres requires a partitioned table's primary key to include the partition
    # key column, so `occurred_at` joins `id` in the PK (autoincrement kept on `id`
    # explicitly, since it's no longer the sole PK column).
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    actor_ip: Mapped[str] = mapped_column(INET)
    event_type: Mapped[str]
    client_id: Mapped[str | None]
    session_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("sessions.id"))
    outcome: Mapped[Outcome] = mapped_column(Enum(Outcome, name="outcome"))
    detail: Mapped[dict[str, Any]] = mapped_column(JSONB)
    request_id: Mapped[str]

class RateLimits(Base):
    __tablename__ = "rate_limits"
    bucket: Mapped[str] = mapped_column(primary_key=True)
    count: Mapped[int] = mapped_column(server_default="0")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
