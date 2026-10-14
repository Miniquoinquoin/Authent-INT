"""
Brute force (architecture.md §4): MAX_FAILURES wrong passwords in a row lock the
account for LOCKOUT. While locked, the answer is the same for a right and a wrong
password, otherwise the attacker would keep guessing through the lock.
"""

from datetime import UTC
from datetime import datetime
from datetime import timedelta

import pytest

from authentint.flows import login
from authentint.flows.login import AccountLocked
from authentint.infra.models.identity import UserStatus


async def fail(s, alice, times: int):
    for _ in range(times):
        assert await login.authenticate(s, alice.numero_fiscal, "wrong") is None


async def test_four_failures_do_not_lock(s, alice, alice_password):
    await fail(s, alice, 4)
    assert await login.authenticate(s, alice.numero_fiscal, alice_password) == alice

async def test_the_fifth_failure_locks(s, alice, alice_password):
    await fail(s, alice, 5)
    with pytest.raises(AccountLocked):
        await login.authenticate(s, alice.numero_fiscal, alice_password)

async def test_a_locked_account_hides_whether_the_password_is_right(s, alice, alice_password):
    await fail(s, alice, 5)
    for password in (alice_password, "wrong"):
        with pytest.raises(AccountLocked):
            await login.authenticate(s, alice.numero_fiscal, password)

async def test_a_success_forgives_previous_failures(s, alice, alice_password):
    await fail(s, alice, 4)
    await login.authenticate(s, alice.numero_fiscal, alice_password)
    await fail(s, alice, 4)
    assert await login.authenticate(s, alice.numero_fiscal, alice_password) == alice

async def test_the_lock_expires(s, alice, alice_password):
    await fail(s, alice, 5)
    alice.locked_until = datetime.now(UTC) - timedelta(seconds=1)  # 15 minutes later...
    assert await login.authenticate(s, alice.numero_fiscal, alice_password) == alice

async def test_an_admin_lock_has_no_expiry(s, alice, alice_password):
    alice.status = UserStatus.locked
    with pytest.raises(AccountLocked):
        await login.authenticate(s, alice.numero_fiscal, alice_password)

async def test_the_route_answers_423(client, authorize_params, alice, alice_password):
    r = await client.get("/authorize", params=authorize_params())
    uid = r.headers["location"].split("uid=")[1]
    for _ in range(5):
        r = await client.post(f"/interaction/{uid}/login", json={"numero_fiscal": alice.numero_fiscal, "password": "wrong"})
        assert r.status_code == 401
    r = await client.post(f"/interaction/{uid}/login", json={"numero_fiscal": alice.numero_fiscal, "password": alice_password})
    assert r.status_code == 423
    assert "set-cookie" not in r.headers
