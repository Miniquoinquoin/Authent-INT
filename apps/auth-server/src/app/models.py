"""Columns, enums, constraints. No logic, no queries (§10)."""

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import (
    ARRAY,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import CITEXT, INET
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Role(StrEnum):
    ADMIN = "admin"
    AGENT = "agent"
    CONTRIBUABLE = "contribuable"


class Status(StrEnum):
    PENDING_ACTIVATION = "pending_activation"
    ACTIVE = "active"
    LOCKED = "locked"
    DISABLED = "disabled"


def _enum(cls: type[StrEnum], name: str) -> Enum:
    # values_callable: store the value, not the Python member name.
    return Enum(cls, name=name, values_callable=lambda e: [m.value for m in e])


_TZ = DateTime(timezone=True)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    #: The directory join key — LDAP `entryUUID`, never the DN (§5b).
    external_id: Mapped[str | None] = mapped_column(Text, unique=True)
    #: Login identifier, never the `sub`. Plaintext for now; §5 wants it
    #: protected at rest and §17 Q3 decides how.
    numero_fiscal: Mapped[str] = mapped_column(Text, unique=True)
    #: The 2FA destination. citext, so case never forks an account.
    email: Mapped[str] = mapped_column(CITEXT, unique=True)
    nom: Mapped[str] = mapped_column(Text)
    prenom: Mapped[str] = mapped_column(Text)
    #: null = pending_activation. Ours, not LDAP's — the directory is read-only
    #: so the credential store has to be ours (§5b).
    password_hash: Mapped[str | None] = mapped_column(Text)
    role: Mapped[Role] = mapped_column(_enum(Role, "user_role"))
    status: Mapped[Status] = mapped_column(_enum(Status, "user_status"))

    password_changed_at: Mapped[datetime | None] = mapped_column(_TZ)
    failed_login_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    locked_until: Mapped[datetime | None] = mapped_column(_TZ)
    synced_at: Mapped[datetime | None] = mapped_column(_TZ)

    created_at: Mapped[datetime] = mapped_column(_TZ, server_default=func.now())
    #: When the user data last changed. Deliberately not `onupdate=now()`:
    #: the sync job stamps `synced_at` on every run, and an automatic
    #: `updated_at` would then mean "when sync last ran" for every row.
    updated_at: Mapped[datetime] = mapped_column(_TZ, server_default=func.now())

    __table_args__ = (
        # The invariant is one-directional: an account awaiting activation has
        # no password, an active one has a password. `locked` and `disabled`
        # say nothing either way — an entry can vanish from the directory
        # before it was ever activated.
        CheckConstraint(
            """(
                status = 'pending_activation' AND password_hash IS NULL
                OR status = 'active' AND password_hash IS NOT NULL
                OR status IN ('locked', 'disabled')
            )""",
            name="ck_users_password_matches_status",
        ),
    )


class ActivationToken(Base):
    __tablename__ = "activation_tokens"

    id: Mapped[uuid.UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    #: The **hash**. If the database leaks, the token must be inert (§6).
    token_hash: Mapped[str] = mapped_column(Text, unique=True)
    expires_at: Mapped[datetime] = mapped_column(_TZ)
    consumed_at: Mapped[datetime | None] = mapped_column(_TZ)
    requested_ip: Mapped[str | None] = mapped_column(INET)
    created_at: Mapped[datetime] = mapped_column(_TZ, server_default=func.now())


class Session(Base):
    __tablename__ = "sessions"

    #: Becomes the `sid` claim at B2.
    id: Mapped[uuid.UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    #: The hash of the cookie value — NOT `id`.
    #:
    #: Beyond the columns P§4 lists, and deliberately. `id` becomes a published
    #: `sid` claim at B2; if the cookie carried `id`, anyone holding an ID token
    #: would hold the session cookie. §6's rule ("never store a token in
    #: plaintext") covers this one too. One column now, or a migration plus
    #: every live session invalidated later.
    token_hash: Mapped[str] = mapped_column(Text, unique=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)

    device_label: Mapped[str | None] = mapped_column(Text)
    user_agent: Mapped[str | None] = mapped_column(Text)
    ip_address: Mapped[str | None] = mapped_column(INET)

    created_at: Mapped[datetime] = mapped_column(_TZ, server_default=func.now())
    last_seen_at: Mapped[datetime] = mapped_column(_TZ, server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(_TZ)
    revoked_at: Mapped[datetime | None] = mapped_column(_TZ)
    revocation_reason: Mapped[str | None] = mapped_column(Text)

    #: Written now, read by B2 for free. They are the only proof a Resource
    #: Server will ever have that MFA actually happened (§5), and they cannot
    #: be backfilled onto sessions that already exist.
    acr: Mapped[str] = mapped_column(Text)
    amr: Mapped[list[str]] = mapped_column(ARRAY(Text))
