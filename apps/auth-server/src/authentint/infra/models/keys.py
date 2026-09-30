import enum
from sqlalchemy.orm import Mapped, mapped_column
from authentint.infra.database import Base
from sqlalchemy import Enum
from datetime import datetime
from typing import Any
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy import DateTime
from sqlalchemy import func


class KeyStatus(str, enum.Enum):
    next = "next"
    active = "active"
    retired = "retired"

class SigningKeys(Base):
    __tablename__ = "signing_keys"
    kid: Mapped[str] = mapped_column(primary_key=True)
    alg: Mapped[str] # RS256 should be used
    public_jwk: Mapped[dict[str, Any]] = mapped_column(JSONB)
    private_pem_encrypted: Mapped[str]
    status: Mapped[KeyStatus] = mapped_column(Enum(KeyStatus, name="key_status"))
    not_before: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    not_after: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
