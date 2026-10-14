"""numero fiscal stored as an HMAC only

Revision ID: d98c46d868dd
Revises: f93b4b48fcc6
Create Date: 2026-10-14 12:00:00

users.numero_fiscal (plain text) becomes users.numero_fiscal_hmac. Existing rows are
converted in place, then the plain column is dropped: after this migration the database
no longer holds a single numero fiscal (decision: pseudonymisation, lesson 11).

The HMAC formula is COPIED here on purpose, not imported from authentint: a migration
must give the same result forever, even if the application code changes later.
It must stay identical to security/identifiers.numero_fiscal_digest.
"""
import hashlib
import hmac
import os

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'd98c46d868dd'
down_revision: Union[str, Sequence[str], None] = 'f93b4b48fcc6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _digest(key: str, numero_fiscal: str) -> str:
    return hmac.new(key.encode(), numero_fiscal.encode(), hashlib.sha256).hexdigest()


def upgrade() -> None:
    key = os.environ["NUMERO_FISCAL_KEY"]  # same key as the application: compose gives it to `migrate`

    # 1. the new column, empty for now (NULL allowed while we fill it)
    op.add_column('users', sa.Column('numero_fiscal_hmac', sa.String(), nullable=True))

    # 2. fill it from the plain column, row by row (10 006 users in dev: a few seconds)
    conn = op.get_bind()
    for user_id, numero_fiscal in conn.execute(sa.text("SELECT id, numero_fiscal FROM users")).all():
        conn.execute(sa.text("UPDATE users SET numero_fiscal_hmac = :h WHERE id = :id"),
                     {"h": _digest(key, numero_fiscal), "id": user_id})

    # 3. now every row has it: make it mandatory and unique, like the old column
    op.alter_column('users', 'numero_fiscal_hmac', nullable=False)
    op.create_unique_constraint('users_numero_fiscal_hmac_key', 'users', ['numero_fiscal_hmac'])

    # 4. the plain numeros fiscaux leave the database
    op.drop_column('users', 'numero_fiscal')


def downgrade() -> None:
    # An HMAC can't be reversed: the plain numeros are gone. Restoring them means re-importing
    # from the directory, which is not a schema operation.
    raise NotImplementedError("one-way migration: re-import users from the directory instead")
