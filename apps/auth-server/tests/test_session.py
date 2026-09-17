"""Sessions, the cookie, `/me` and `/logout` — plus the whole path, end to end."""

import re
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.config import settings
from app.models import Session, Status, User
from app.sessions import ACR_MFA, AMR_PASSWORD_AND_OTP
from helpers import ADMIN_NF, PASSWORD, activate_directly, login, reset_rate_limits, seed

CODE = re.compile(r"\b(\d{6})\b")
TOKEN = re.compile(r"/activer\?token=([\w\-]+)")


@pytest.fixture(autouse=True)
async def users(db, fixture_file):
    await seed(db, fixture_file)


async def full_login(client, inbox, numero_fiscal: str = ADMIN_NF, password: str = PASSWORD):
    await reset_rate_limits()
    uid = (await client.post("/interaction")).json()["uid"]
    assert (await login(client, numero_fiscal, password, uid=uid)).json() == {"stage": "mfa"}
    await client.post(f"/interaction/{uid}/mfa/send")
    code = CODE.search(inbox.latest_body()).group(1)
    return await client.post(f"/interaction/{uid}/mfa/verify", json={"code": code})


async def test_the_whole_path_end_to_end(client, db, inbox):
    """sync → activate → login → OTP → /me.

    Nothing is stubbed: the activation token is read out of the mail Mailpit
    actually received, and the OTP out of the second one.
    """
    # The account arrives from the directory with no password. Attempting to log
    # in is what triggers the activation mail — there is no request endpoint.
    assert (await login(client, ADMIN_NF)).status_code == 401
    token = TOKEN.search(inbox.latest_body()).group(1)

    confirmed = await client.post(
        "/account/activation/confirm", json={"token": token, "password": PASSWORD}
    )
    assert confirmed.status_code == 204

    done = await full_login(client, inbox)
    assert done.json() == {"stage": "done"}

    me = await client.get("/me")
    assert me.status_code == 200
    assert me.json()["prenom"] == "Claire"
    assert me.json()["role"] == "admin"
    assert me.json()["statut"] == "active"


async def test_an_activation_token_is_single_use(client, db, inbox):
    assert (await login(client, ADMIN_NF)).status_code == 401
    token = TOKEN.search(inbox.latest_body()).group(1)
    assert (await client.post("/account/activation/confirm", json={"token": token, "password": PASSWORD})).status_code == 204

    again = await client.post("/account/activation/confirm", json={"token": token, "password": "un autre mot de passe"})

    assert again.status_code == 400


async def test_activating_kills_every_outstanding_token(client, db, inbox):
    """Each login attempt on a pending account mails a fresh token. Using one
    must retire the others, or a sibling stays live for its 30 minutes."""
    assert (await login(client, ADMIN_NF)).status_code == 401
    first = TOKEN.search(inbox.latest_body()).group(1)
    assert (await login(client, ADMIN_NF)).status_code == 401
    second = TOKEN.search(inbox.latest_body()).group(1)
    assert first != second

    assert (await client.post("/account/activation/confirm", json={"token": second, "password": PASSWORD})).status_code == 204

    # Checked on the rows, not through the endpoint: an `active` account is
    # refused there regardless, and the hole is the `locked` state it can reach
    # later, while the sibling token is still inside its 30 minutes.
    from app.models import ActivationToken

    rows = (await db.scalars(select(ActivationToken))).all()
    assert len(rows) == 2
    assert all(r.consumed_at is not None for r in rows), "the sibling token is retired too"


async def test_a_short_password_is_refused(client, inbox):
    assert (await login(client, ADMIN_NF)).status_code == 401
    token = TOKEN.search(inbox.latest_body()).group(1)

    response = await client.post("/account/activation/confirm", json={"token": token, "password": "trop court"})

    assert response.status_code == 422


async def test_the_session_records_how_strongly_it_was_authenticated(client, db, inbox):
    """`acr`/`amr` are written now and read by B2 for free. They are the only
    proof a Resource Server will ever have that MFA happened (§5)."""
    await activate_directly(db, ADMIN_NF)
    await full_login(client, inbox)

    session = await db.scalar(select(Session))
    assert session.acr == ACR_MFA
    assert session.amr == AMR_PASSWORD_AND_OTP
    assert session.device_label


async def test_the_cookie_value_is_not_the_session_id(client, db, inbox):
    """`id` becomes a published `sid` claim at B2. If the cookie carried it,
    every ID token holder would hold the session cookie."""
    await activate_directly(db, ADMIN_NF)
    response = await full_login(client, inbox)

    cookie = response.cookies[settings().cookie_name]
    session = await db.scalar(select(Session))

    assert cookie != str(session.id)
    assert cookie != session.token_hash, "the stored value is a digest of the cookie, not the cookie"


async def test_the_cookie_comes_back_over_plain_http(client, db, inbox):
    """The regression test for the Safari dead-end.

    Everything up to here can pass while login is still broken in a browser:
    `verify` answers 200 and sets a cookie, and the *next* request drops it
    because it is marked `Secure` on a plain-http origin. WebKit does that;
    Chromium does not, which is why it only showed up in one browser.

    Asserting the round trip, not just the `Set-Cookie` header, is the whole
    point — the header was always fine.
    """
    await activate_directly(db, ADMIN_NF)
    response = await full_login(client, inbox)

    cookie = response.headers["set-cookie"]
    assert "Secure" not in cookie, "a Secure cookie is unusable on this origin"
    assert not cookie.startswith("__Host-"), "the prefix is only legal with Secure"

    assert (await client.get("/me")).status_code == 200, "the cookie must actually come back"


async def test_https_hardens_the_cookie(client, db, inbox, monkeypatch):
    """And the derivation goes the other way on its own.

    The day `PUBLIC_BASE_URL` becomes https — the day Caddy lands — the cookie
    becomes `__Host-` + `Secure` with no code change and no env var to remember.
    """
    monkeypatch.setattr(settings(), "public_base_url", "https://login.authentint.local")
    await activate_directly(db, ADMIN_NF)

    response = await full_login(client, inbox)

    cookie = response.headers["set-cookie"]
    assert cookie.startswith("__Host-session=")
    assert "Secure" in cookie


async def test_me_without_a_cookie_is_refused(client):
    assert (await client.get("/me")).status_code == 401


async def test_logout_kills_the_session(client, db, inbox):
    await activate_directly(db, ADMIN_NF)
    await full_login(client, inbox)
    assert (await client.get("/me")).status_code == 200

    assert (await client.post("/logout")).status_code == 204

    assert (await client.get("/me")).status_code == 401
    session = await db.scalar(select(Session))
    assert session.revoked_at is not None, "the row is revoked, not just the cookie cleared"
    assert session.revocation_reason == "logout"


async def test_a_revoked_session_does_not_resolve_even_with_the_cookie(client, db, inbox):
    """The cookie is a hint; the row is the truth. Postgres is the source of
    truth for sessions, so revocation survives a Valkey restart (§11b)."""
    await activate_directly(db, ADMIN_NF)
    await full_login(client, inbox)
    session = await db.scalar(select(Session))
    session.revoked_at = datetime.now(UTC)
    await db.commit()

    assert (await client.get("/me")).status_code == 401


async def test_an_idle_session_expires(client, db, inbox):
    await activate_directly(db, ADMIN_NF)
    await full_login(client, inbox)
    session = await db.scalar(select(Session))
    session.last_seen_at = datetime.now(UTC) - timedelta(seconds=settings().session_idle_ttl_s + 60)
    await db.commit()

    assert (await client.get("/me")).status_code == 401


async def test_an_absolute_deadline_ends_the_session(client, db, inbox):
    await activate_directly(db, ADMIN_NF)
    await full_login(client, inbox)
    session = await db.scalar(select(Session))
    session.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    await db.commit()

    assert (await client.get("/me")).status_code == 401


async def test_disabling_the_account_ends_the_session(client, db, inbox):
    """A directory entry that vanished must not keep a live session working."""
    await activate_directly(db, ADMIN_NF)
    await full_login(client, inbox)
    user = await db.scalar(select(User).where(User.numero_fiscal == ADMIN_NF))
    user.status = Status.DISABLED
    await db.commit()

    assert (await client.get("/me")).status_code == 401
