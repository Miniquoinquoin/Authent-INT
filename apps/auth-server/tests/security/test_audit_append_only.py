"""
Invariant 10 (ADR §8, §16): the audit trail is append-only at the DATABASE level. The tests
connect as auth-server does (authentint_app): it may INSERT, but UPDATE, DELETE and TRUNCATE
are refused by Postgres itself, on the table and on its partition.
"""

import pytest

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from authentint.audit import audit


async def refused(s, sql: str) -> None:
    """`sql` fails with insufficient_privilege; the savepoint keeps the test's transaction usable."""

    with pytest.raises(DBAPIError) as e:
        async with s.begin_nested():
            await s.execute(text(sql))
    assert e.value.orig.sqlstate == "42501"  # insufficient_privilege


async def test_the_app_role_is_not_a_superuser(s):
    assert await s.scalar(text("SELECT rolsuper FROM pg_roles WHERE rolname = current_user")) is False
    assert await s.scalar(text("SELECT current_user")) == "authentint_app"

async def test_the_app_role_owns_nothing(s):
    owned = await s.scalar(text("SELECT count(*) FROM pg_class WHERE relowner = (SELECT oid FROM pg_roles WHERE rolname = current_user)"))
    assert owned == 0

async def test_insert_works_and_is_routed_to_the_partition(s):
    await audit.emit(s, "test.append_only", actor=None, outcome="success", detail={})
    await s.flush()
    # read through the parent: the app has no privilege at all on audit_events_default
    assert await s.scalar(text("SELECT count(*) FROM audit_events WHERE event_type = 'test.append_only'")) == 1

async def test_update_is_refused(s):
    await refused(s, "UPDATE audit_events SET outcome = 'success'")

async def test_delete_is_refused(s):
    await refused(s, "DELETE FROM audit_events")

async def test_truncate_is_refused(s):
    await refused(s, "TRUNCATE audit_events")

async def test_the_partition_is_no_back_door(s):
    await refused(s, "UPDATE audit_events_default SET outcome = 'success'")
    await refused(s, "DELETE FROM audit_events_default")
