import uuid
import enum
from sqlalchemy.orm import Mapped, mapped_column
from authentint.infra.database import Base
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy import Enum
from datetime import datetime
from sqlalchemy.dialects.postgresql import INET
from sqlalchemy import DateTime
from sqlalchemy import func
from sqlalchemy import ForeignKey


class Role(str, enum.Enum):
    admin = "admin"
    agent = "agent"
    contribuable = "contribuable"

class UserStatus(str, enum.Enum):
    pending_activation = "pending_activation"
    active = "active"
    locked = "locked"
    disabled = "disabled"

class User(Base):
    __tablename__ = "users"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    external_id: Mapped[str | None] = mapped_column(unique=True)
    numero_fiscal: Mapped[str] = mapped_column(unique=True)
    email: Mapped[str]
    nom: Mapped[str]
    prenom: Mapped[str]
    password_hash: Mapped[str | None]
    role: Mapped[Role] = mapped_column(Enum(Role, name="user_role"))
    status: Mapped[UserStatus] = mapped_column(Enum(UserStatus, name="user_status"))
    password_changed_at: Mapped[datetime | None]
    failed_login_count: Mapped[int] = mapped_column(default=0, server_default="0")
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

class ActivationTokens(Base):
    __tablename__ = "activation_tokens"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    token_hash: Mapped[str] = mapped_column(unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    requested_ip: Mapped[str] = mapped_column(INET)

class PasswordResetTokens(Base):
    __tablename__ = "password_reset_tokens"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    token_hash: Mapped[str] = mapped_column(unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    requested_ip: Mapped[str] = mapped_column(INET)
