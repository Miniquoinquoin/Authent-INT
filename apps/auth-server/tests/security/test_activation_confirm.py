"""
POST /account/activation/confirm (flows/activation.py) — B1.
A link works once, for 30 minutes, and only the newest outstanding set of links
of a user can activate it. Ends with B1's "done when": seeded → activated → logged in.
"""

import re

from datetime import UTC
from datetime import datetime
from datetime import timedelta

from sqlalchemy import select

from authentint.infra.models.identity import ActivationTokens
from authentint.infra.models.identity import UserStatus

NEW_PASSWORD = "Une-phrase-assez-longue"


async def link_for(client, mailbox, user) -> str:
    """Asks an activation link for `user` and returns the token it carries."""

    await client.post("/account/activation/request", json={"numero_fiscal": user.numero_fiscal})
    return re.search(r"token=([\w-]+)", mailbox.sent[-1]["body"]).group(1)

async def confirm(client, token: str, password: str = NEW_PASSWORD):
    return await client.post("/account/activation/confirm", json={"token": token, "password": password})


async def test_a_valid_link_activates_the_account(client, s, mailbox, bob):
    r = await confirm(client, await link_for(client, mailbox, bob))
    assert r.status_code == 200
    await s.refresh(bob)
    assert bob.status == UserStatus.active
    assert bob.password_hash.startswith("$argon2id$")  # stored as Argon2, never as typed

async def test_seeded_then_activated_then_logged_in(client, mailbox, bob, authorize_params):
    # B1 "done when" (ADR §17): a directory user, never activated, ends up logged in
    await confirm(client, await link_for(client, mailbox, bob))
    r = await client.get("/authorize", params=authorize_params())
    uid = r.headers["location"].split("uid=")[1]
    r = await client.post(f"/interaction/{uid}/login", json={"numero_fiscal": bob.numero_fiscal, "password": NEW_PASSWORD})
    assert r.status_code == 200

async def test_a_link_works_only_once(client, mailbox, bob):
    token = await link_for(client, mailbox, bob)
    assert (await confirm(client, token)).status_code == 200
    assert (await confirm(client, token, "Un-autre-mot-de-passe")).status_code == 400

async def test_using_one_link_kills_the_others(client, mailbox, bob):
    first = await link_for(client, mailbox, bob)
    second = await link_for(client, mailbox, bob)
    assert (await confirm(client, second)).status_code == 200
    assert (await confirm(client, first, "Un-autre-mot-de-passe")).status_code == 400

async def test_an_expired_link_is_refused(client, s, mailbox, bob):
    token = await link_for(client, mailbox, bob)
    [row] = await s.scalars(select(ActivationTokens).where(ActivationTokens.user_id == bob.id))
    row.expires_at = datetime.now(UTC) - timedelta(hours=1)  # an hour after the 30 minutes
    assert (await confirm(client, token)).status_code == 400

async def test_an_invented_token_is_refused(client, bob):
    assert (await confirm(client, "this-token-was-never-sent")).status_code == 400

async def test_a_short_password_is_refused(client, mailbox, bob):
    r = await confirm(client, await link_for(client, mailbox, bob), password="court")
    assert r.status_code == 422
