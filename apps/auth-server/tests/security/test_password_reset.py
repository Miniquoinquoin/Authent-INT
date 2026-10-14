"""
/account/password-reset/* (flows/reset.py) — B1.
Same guarantees as activation, plus: the reset closes every session opened with
the old password, and lifts the lockout.
"""

import re

from datetime import UTC
from datetime import datetime
from datetime import timedelta

from sqlalchemy import select

from authentint.infra.models.audit import Sessions
from authentint.infra.models.identity import PasswordResetTokens

NEW_PASSWORD = "Une-nouvelle-phrase-longue"


async def link_for(client, mailbox, user) -> str:
    await client.post("/account/password-reset/request", json={"numero_fiscal": user.numero_fiscal})
    return re.search(r"token=([\w-]+)", mailbox.sent[-1]["body"]).group(1)

async def reset(client, token: str, password: str = NEW_PASSWORD):
    return await client.post("/account/password-reset/confirm", json={"token": token, "password": password})

async def login(client, authorize_params, user, password: str):
    client.cookies.clear()
    r = await client.get("/authorize", params=authorize_params())
    uid = r.headers["location"].split("uid=")[1]
    return await client.post(f"/interaction/{uid}/login", json={"numero_fiscal": user.numero_fiscal, "password": password})


async def test_the_answer_never_tells_whether_the_account_exists(client, mailbox, alice, bob):
    answers = [await client.post("/account/password-reset/request", json={"numero_fiscal": nf})
               for nf in (alice.numero_fiscal, bob.numero_fiscal, "1800000000000")]  # active, pending, unknown
    assert {r.status_code for r in answers} == {202}
    assert answers[0].json() == answers[1].json() == answers[2].json()
    assert [m["to"] for m in mailbox.sent] == [alice.email]  # only the active account gets a link

async def test_the_new_password_works_and_the_old_one_no_longer(client, mailbox, alice, alice_password, authorize_params):
    assert (await reset(client, await link_for(client, mailbox, alice))).status_code == 200
    assert (await login(client, authorize_params, alice, NEW_PASSWORD)).status_code == 200
    assert (await login(client, authorize_params, alice, alice_password)).status_code == 401

async def test_a_link_works_only_once(client, mailbox, alice):
    # here the account stays `active` after use: only `consumed_at` stops a second use
    token = await link_for(client, mailbox, alice)
    assert (await reset(client, token)).status_code == 200
    assert (await reset(client, token, "Encore-un-autre-mot-de-passe")).status_code == 400

async def test_an_expired_link_is_refused(client, s, mailbox, alice):
    token = await link_for(client, mailbox, alice)
    [row] = await s.scalars(select(PasswordResetTokens).where(PasswordResetTokens.user_id == alice.id))
    row.expires_at = datetime.now(UTC) - timedelta(hours=1)
    assert (await reset(client, token)).status_code == 400

async def test_a_reset_lifts_the_lockout(client, mailbox, alice, authorize_params):
    alice.locked_until = datetime.now(UTC) + timedelta(minutes=10)
    await reset(client, await link_for(client, mailbox, alice))
    assert (await login(client, authorize_params, alice, NEW_PASSWORD)).status_code == 200

async def test_a_reset_logs_out_every_device(client, s, mailbox, alice, alice_password, authorize_params):
    await login(client, authorize_params, alice, alice_password)  # alice's phone...
    await login(client, authorize_params, alice, alice_password)  # ...and someone who stole her password
    await reset(client, await link_for(client, mailbox, alice))
    open_sessions = list(await s.scalars(select(Sessions).where(Sessions.user_id == alice.id, Sessions.revoked_at.is_(None))))
    assert open_sessions == []  # both are closed: the thief is out

async def test_a_reset_does_not_rewrite_the_history_of_closed_sessions(client, s, mailbox, alice, alice_password, authorize_params):
    await login(client, authorize_params, alice, alice_password)
    [old] = await s.scalars(select(Sessions).where(Sessions.user_id == alice.id))
    closed_on = datetime(2026, 10, 3, 18, 0, tzinfo=UTC)
    old.revoked_at, old.revocation_reason = closed_on, "logout"  # alice logged out of her old laptop on Oct 3
    await login(client, authorize_params, alice, alice_password)  # today's session, still open
    await reset(client, await link_for(client, mailbox, alice))
    await s.refresh(old)
    assert (old.revoked_at, old.revocation_reason) == (closed_on, "logout")  # the past is untouched
    [today] = await s.scalars(select(Sessions).where(Sessions.user_id == alice.id, Sessions.id != old.id))
    assert today.revocation_reason == "password_reset"  # and the history says why this one closed
