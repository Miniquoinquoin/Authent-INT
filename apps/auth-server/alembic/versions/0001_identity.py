"""Phase-1 identity tables: users, activation_tokens, sessions.

Only the phase-1 tables. The OAuth tables of §6 land in their own revision when
B2 starts — versioned migrations exist precisely so the schema arrives in the
order the code needs it (P§4).

Revision ID: 0001_identity
Revises:
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_identity"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# create_type=False: the types are created once, explicitly, below. Left to
# itself SQLAlchemy emits CREATE TYPE again for every column that uses one.
ROLE = postgresql.ENUM("admin", "agent", "contribuable", name="user_role", create_type=False)
STATUS = postgresql.ENUM(
    "pending_activation", "active", "locked", "disabled", name="user_status", create_type=False
)
TZ = sa.DateTime(timezone=True)


def upgrade() -> None:
    # citext gives us an e-mail column where case cannot fork an account.
    op.execute("CREATE EXTENSION IF NOT EXISTS citext")

    bind = op.get_bind()
    ROLE.create(bind, checkfirst=True)
    STATUS.create(bind, checkfirst=True)

    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("external_id", sa.Text(), unique=True),
        sa.Column("numero_fiscal", sa.Text(), nullable=False, unique=True),
        sa.Column("email", postgresql.CITEXT(), nullable=False, unique=True),
        sa.Column("nom", sa.Text(), nullable=False),
        sa.Column("prenom", sa.Text(), nullable=False),
        sa.Column("password_hash", sa.Text()),
        sa.Column("role", ROLE, nullable=False),
        sa.Column("status", STATUS, nullable=False),
        sa.Column("password_changed_at", TZ),
        sa.Column("failed_login_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("locked_until", TZ),
        sa.Column("synced_at", TZ),
        sa.Column("created_at", TZ, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", TZ, nullable=False, server_default=sa.func.now()),
        # Awaiting activation => no password; active => a password. `locked`
        # and `disabled` say nothing either way: an entry can vanish from the
        # directory before it was ever activated.
        sa.CheckConstraint(
            """(
                status = 'pending_activation' AND password_hash IS NULL
                OR status = 'active' AND password_hash IS NOT NULL
                OR status IN ('locked', 'disabled')
            )""",
            name="ck_users_password_matches_status",
        ),
    )

    op.create_table(
        "activation_tokens",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("token_hash", sa.Text(), nullable=False, unique=True),
        sa.Column("expires_at", TZ, nullable=False),
        sa.Column("consumed_at", TZ),
        sa.Column("requested_ip", postgresql.INET()),
        sa.Column("created_at", TZ, nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_activation_tokens_user_id", "activation_tokens", ["user_id"])

    op.create_table(
        "sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("token_hash", sa.Text(), nullable=False, unique=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("device_label", sa.Text()),
        sa.Column("user_agent", sa.Text()),
        sa.Column("ip_address", postgresql.INET()),
        sa.Column("created_at", TZ, nullable=False, server_default=sa.func.now()),
        sa.Column("last_seen_at", TZ, nullable=False, server_default=sa.func.now()),
        sa.Column("expires_at", TZ, nullable=False),
        sa.Column("revoked_at", TZ),
        sa.Column("revocation_reason", sa.Text()),
        sa.Column("acr", sa.Text(), nullable=False),
        sa.Column("amr", postgresql.ARRAY(sa.Text()), nullable=False),
    )
    op.create_index("ix_sessions_user_id", "sessions", ["user_id"])


def downgrade() -> None:
    op.drop_table("sessions")
    op.drop_table("activation_tokens")
    op.drop_table("users")
    bind = op.get_bind()
    STATUS.drop(bind, checkfirst=True)
    ROLE.drop(bind, checkfirst=True)
