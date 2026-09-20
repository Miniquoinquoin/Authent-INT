import uuid
import enum
from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column
from authentint.infra.database import Base
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy import Enum
from datetime import datetime
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy import DateTime
from sqlalchemy import func
from sqlalchemy import ForeignKey


class ClientType(str, enum.Enum):
    public = "public"
    confidential = "confidential"

class OAuthClients(Base):
    __tablename__ = "clients"
    id: Mapped[str] = mapped_column(primary_key=True)
    name: Mapped[str]
    type: Mapped[ClientType] = mapped_column(Enum(ClientType, name="client_type"))
    secret_hash: Mapped[str | None]
    redirect_uris: Mapped[list[str]] = mapped_column(ARRAY(String))
    post_logout_redirect_uris: Mapped[list[str]] = mapped_column(ARRAY(String))
    allowed_grants: Mapped[list[str]] = mapped_column(ARRAY(String))
    allowed_scopes: Mapped[list[str]] = mapped_column(ARRAY(String))
    require_consent: Mapped[bool]

class OAuthInteractions(Base):
    __tablename__ = "interactions"
    uid: Mapped[str] = mapped_column(primary_key=True)
    client_id: Mapped[str] = mapped_column(ForeignKey("clients.id"))
    redirect_uri: Mapped[str]
    scope: Mapped[str]
    state: Mapped[str]
    nonce: Mapped[str]
    code_challenge: Mapped[str]
    code_challenge_method: Mapped[str]
    stage: Mapped[str]
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

class OAuthAuthorizationCodes(Base):
    __tablename__ = "authorization_codes"
    code_hash: Mapped[str] = mapped_column(primary_key=True)
    client_id: Mapped[str] = mapped_column(ForeignKey("clients.id"))
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    session_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sessions.id"))
    redirect_uri: Mapped[str]
    scope: Mapped[str]
    nonce: Mapped[str]
    code_challenge: Mapped[str]
    code_challenge_method: Mapped[str]
    auth_time: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    acr: Mapped[str]
    amr: Mapped[list[str]] = mapped_column(ARRAY(String))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

class OAuthRefreshTokens(Base):
    __tablename__ = "refresh_tokens"
    token_hash: Mapped[str] = mapped_column(primary_key=True)
    family_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), default=uuid.uuid4)
    parent_hash: Mapped[str | None] = mapped_column(ForeignKey("refresh_tokens.token_hash"))
    client_id: Mapped[str] = mapped_column(ForeignKey("clients.id"))
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    session_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sessions.id"))
    scope: Mapped[str]
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    rotated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revocation_reason: Mapped[str | None]

class OAuthConsents(Base):
    __tablename__ = "consents"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    client_id: Mapped[str] = mapped_column(ForeignKey("clients.id"))
    scopes: Mapped[list[str]] = mapped_column(ARRAY(String))
    granted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
