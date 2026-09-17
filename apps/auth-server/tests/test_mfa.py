"""E-mail OTP: the second factor, and the things it must never say."""

import re

import pytest

from app.config import settings
from helpers import ADMIN_NF, AGENT_NF, activate_directly, login, reset_rate_limits, seed

CODE = re.compile(r"\b(\d{6})\b")


@pytest.fixture(autouse=True)
async def users(db, fixture_file):
    await seed(db, fixture_file)


async def reach_mfa(client, db, numero_fiscal: str = ADMIN_NF) -> str:
    """Log in for real and stop at the MFA stage."""
    await activate_directly(db, numero_fiscal)
    await reset_rate_limits()
    uid = (await client.post("/interaction")).json()["uid"]
    response = await login(client, numero_fiscal, uid=uid)
    assert response.json() == {"stage": "mfa"}
    return uid


async def send_and_read(client, inbox, uid: str) -> str:
    assert (await client.post(f"/interaction/{uid}/mfa/send")).status_code == 200
    return CODE.search(inbox.latest_body()).group(1)


async def test_otp_completes_the_flow_and_sets_the_cookie(client, db, inbox):
    uid = await reach_mfa(client, db)
    code = await send_and_read(client, inbox, uid)

    response = await client.post(f"/interaction/{uid}/mfa/verify", json={"code": code})

    assert response.status_code == 200
    assert response.json() == {"stage": "done"}
    assert settings().cookie_name in response.cookies


async def test_the_code_is_never_stored_in_plaintext(client, db, inbox):
    """§6: if the store leaks, the challenge must be inert."""
    from app.infra import cache

    uid = await reach_mfa(client, db)
    code = await send_and_read(client, inbox, uid)

    stored = await cache.otp_get(uid)

    assert code not in str(stored)
    assert stored["code_hash"].startswith("$argon2")


async def test_five_wrong_attempts_consume_the_challenge(client, db, inbox):
    uid = await reach_mfa(client, db)
    code = await send_and_read(client, inbox, uid)
    wrong = "000000" if code != "000000" else "111111"

    for _ in range(settings().otp_max_attempts):
        assert (await client.post(f"/interaction/{uid}/mfa/verify", json={"code": wrong})).status_code == 401

    # Consumed on exhaustion as well as on success (§9): even the right code is
    # dead now, which is what stops a brute force from simply continuing.
    assert (await client.post(f"/interaction/{uid}/mfa/verify", json={"code": code})).status_code == 401
    from app.infra import cache

    assert await cache.otp_get(uid) is None


async def test_wrong_and_expired_are_indistinguishable(client, db, inbox):
    """Never reveal whether the code was wrong or expired (§9)."""
    from app.infra import cache

    uid = await reach_mfa(client, db)
    code = await send_and_read(client, inbox, uid)
    wrong = await client.post(f"/interaction/{uid}/mfa/verify", json={"code": "000000" if code != "000000" else "111111"})

    await cache.otp_consume(uid)  # exactly what expiry leaves behind
    expired = await client.post(f"/interaction/{uid}/mfa/verify", json={"code": code})

    assert wrong.content == expired.content
    assert wrong.status_code == expired.status_code


async def test_a_code_cannot_be_replayed_against_another_interaction(client, db, inbox):
    """The OTP is bound to the `uid` (§9)."""
    first = await reach_mfa(client, db, ADMIN_NF)
    code = await send_and_read(client, inbox, first)

    second = await reach_mfa(client, db, AGENT_NF)
    await send_and_read(client, inbox, second)

    response = await client.post(f"/interaction/{second}/mfa/verify", json={"code": code})

    assert response.status_code == 401


async def test_mail_failure_fails_loudly_and_never_skips_mfa(client, db, monkeypatch):
    """§11.6: a mail outage degrades into "you cannot log in", never into
    "you are logged in"."""
    import smtplib

    from app.infra import mailer

    uid = await reach_mfa(client, db)

    def dead(_message):
        raise smtplib.SMTPException("relay unreachable")

    monkeypatch.setattr(mailer, "_send", dead)

    response = await client.post(f"/interaction/{uid}/mfa/send")

    assert response.status_code == 502
    assert (await client.get(f"/interaction/{uid}")).json() == {"stage": "mfa"}, "still stuck at MFA"


async def test_verify_before_send_is_refused(client, db):
    uid = await reach_mfa(client, db)

    response = await client.post(f"/interaction/{uid}/mfa/verify", json={"code": "123456"})

    assert response.status_code == 401


async def test_login_stage_cannot_be_skipped(client, db):
    """Never trust the client's claim about which stage it is on (§8 step 8)."""
    await activate_directly(db, ADMIN_NF)
    uid = (await client.post("/interaction")).json()["uid"]

    assert (await client.post(f"/interaction/{uid}/mfa/send")).status_code == 410
    assert (await client.post(f"/interaction/{uid}/mfa/verify", json={"code": "123456"})).status_code == 410
