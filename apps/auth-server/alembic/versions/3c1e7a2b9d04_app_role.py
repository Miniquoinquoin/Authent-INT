"""runtime role authentint_app: no ownership, audit append-only

Revision ID: 3c1e7a2b9d04
Revises: d98c46d868dd
Create Date: 2026-10-14 18:00:00

ADR §8 / §16 "Audit append-only au niveau des privilèges base". A REVOKE means nothing
against the owner or a superuser, so two roles:
- authentint_owner (POSTGRES_USER, superuser of the container) owns the schema and runs `migrate`;
- authentint_app, created here, is what auth-server connects as: plain DML, owns nothing,
  and on audit_events only SELECT + INSERT. Even a SQL injection can't rewrite the trail.

The password comes from APP_DB_PASSWORD (compose gives it to `migrate`).
"""
import os

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '3c1e7a2b9d04'
down_revision: Union[str, Sequence[str], None] = 'd98c46d868dd'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # CREATE ROLE takes no bind parameter: the password travels as a transaction-local
    # setting and is quoted by format('%L') server side, never spliced into SQL here
    op.get_bind().execute(sa.text("SELECT set_config('authentint.app_password', :pw, true)"),
                          {"pw": os.environ["APP_DB_PASSWORD"]})
    op.execute("""
    DO $$
    BEGIN
        IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'authentint_app') THEN
            EXECUTE format('CREATE ROLE authentint_app LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD %L',
                           current_setting('authentint.app_password'));
        ELSE
            -- an older volume where it was the superuser: demote it, the password follows the env
            EXECUTE format('ALTER ROLE authentint_app LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD %L',
                           current_setting('authentint.app_password'));
        END IF;
        EXECUTE format('GRANT CONNECT ON DATABASE %I TO authentint_app', current_database());
    END
    $$
    """)
    op.execute("GRANT USAGE ON SCHEMA public TO authentint_app")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO authentint_app")
    op.execute("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO authentint_app")
    # Tables of future migrations are created by the owner (current_user here) and granted the same way
    op.execute("ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO authentint_app")
    op.execute("ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO authentint_app")

    # The append-only rule. TRUNCATE was never granted; revoked anyway, so reading this is enough.
    op.execute("REVOKE UPDATE, DELETE, TRUNCATE ON audit_events FROM authentint_app")
    # Inserts through the parent are routed without any privilege on the partition (checked on the
    # parent only), so the partition gets nothing: no back door to UPDATE it directly.
    # WARNING: a future partition inherits the default privileges above: REVOKE ALL on it too.
    op.execute("REVOKE ALL ON audit_events_default FROM authentint_app")
    # The app has no business with the migration history
    op.execute("REVOKE ALL ON alembic_version FROM authentint_app")


def downgrade() -> None:
    # Revokes every grant and default privilege of the role in this database, then the role goes
    op.execute("DROP OWNED BY authentint_app")
    op.execute("DROP ROLE authentint_app")
