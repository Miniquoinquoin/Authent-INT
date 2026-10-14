"""
Traceability (brief: "traçabilité totale"): every login attempt leaves an audit event,
and no event ever contains the numero fiscal or the password (invariant 7).
"""

import pytest

from sqlalchemy import func
from sqlalchemy import select

from authentint.infra.models.audit import AuditEvents


@pytest.fixture
async def since(s) -> int:
    """The last audit id before the test. The table is append-only: rows from earlier
    runs and real logins stay forever, so a test only ever looks at the rows it created."""

    return await s.scalar(select(func.coalesce(func.max(AuditEvents.id), 0)))

async def events(s, since: int, event_type: str | None = None) -> list[AuditEvents]:
    query = select(AuditEvents).where(AuditEvents.id > since)
    if event_type is not None:
        query = query.where(AuditEvents.event_type == event_type)
    return list(await s.scalars(query))

async def login(client, authorize_params, numero_fiscal: str, password: str):
    r = await client.get("/authorize", params=authorize_params())
    uid = r.headers["location"].split("uid=")[1]
    return await client.post(f"/interaction/{uid}/login", json={"numero_fiscal": numero_fiscal, "password": password})


async def test_success_is_recorded_with_the_session(client, s, since, authorize_params, alice, alice_password):
    r = await login(client, authorize_params, alice.numero_fiscal, alice_password)
    [event] = await events(s, since, "login.success")
    assert event.actor_user_id == alice.id
    assert event.detail["sid"]  # which session: lets /me/sessions and the audit point at each other
    assert event.request_id == r.headers["x-request-id"]  # one id joins this row to the request's logs

async def test_wrong_password_is_recorded_against_the_account(client, s, since, authorize_params, alice):
    await login(client, authorize_params, alice.numero_fiscal, "wrong")
    [event] = await events(s, since, "login.failure")
    assert event.actor_user_id == alice.id  # alice will see it in /me/audit: "someone tried your account"
    assert event.outcome == "failure"

async def test_unknown_numero_fiscal_is_recorded_without_actor(client, s, since, authorize_params, alice):
    await login(client, authorize_params, "1809999999999", "whatever")
    [event] = await events(s, since, "login.failure")
    assert event.actor_user_id is None

async def test_lock_is_recorded(client, s, since, authorize_params, alice, alice_password):
    for _ in range(5):
        await login(client, authorize_params, alice.numero_fiscal, "wrong")
    await login(client, authorize_params, alice.numero_fiscal, alice_password)
    [event] = await events(s, since, "login.locked")
    assert event.actor_user_id == alice.id

async def test_no_event_ever_contains_the_numero_fiscal_or_the_password(client, s, since, authorize_params, alice, alice_password):
    await login(client, authorize_params, alice.numero_fiscal, "Secret-typo-1")
    await login(client, authorize_params, "1809999999999", "Secret-typo-2")
    await login(client, authorize_params, alice.numero_fiscal, alice_password)
    rows = await events(s, since)
    assert len(rows) == 3
    for row in rows:
        dump = f"{row.event_type} {row.detail}"
        for secret in (alice.numero_fiscal, "1809999999999", "Secret-typo-1", "Secret-typo-2", alice_password):
            assert secret not in dump
