"""POST /interaction/{uid}/consent and the remembered consent (ADR §10 step 9) — B1."""

from sqlalchemy import select

from authentint.config import settings
from authentint.infra.models.oauth import OAuthConsents


async def logged_in(client, authorize_params, alice, alice_password, scope="openid svc:impots.read") -> tuple[str, dict]:
    """Starts a flow and logs alice in. Returns the uid and the login answer."""

    client.cookies.clear()  # a fresh browser each time: no SSO cookie from a previous login
    r = await client.get("/authorize", params=authorize_params(scope=scope))
    uid = r.headers["location"].split("uid=")[1]
    r = await client.post(f"/interaction/{uid}/login", json={"numero_fiscal": alice.numero_fiscal, "password": alice_password})
    return uid, r.json()


async def test_a_client_that_requires_consent_asks_for_it(client, spa, authorize_params, alice, alice_password):
    spa.require_consent = True
    _, after_login = await logged_in(client, authorize_params, alice, alice_password)
    assert after_login["prompt"] == "consent"
    assert after_login["scopes"] == ["openid", "svc:impots.read"]  # what the screen shows

async def test_accepting_finishes_the_flow_and_is_stored(client, s, spa, authorize_params, alice, alice_password):
    spa.require_consent = True
    uid, _ = await logged_in(client, authorize_params, alice, alice_password)
    r = await client.post(f"/interaction/{uid}/consent", json={"approve": True})
    assert r.status_code == 200
    assert r.json()["prompt"] is None
    assert r.json()["redirect_to"].startswith(f"{settings.issuer}/authorize?")
    [row] = await s.scalars(select(OAuthConsents).where(OAuthConsents.user_id == alice.id))
    assert set(row.scopes) == {"openid", "svc:impots.read"}

async def test_an_accepted_consent_is_not_asked_again(client, spa, authorize_params, alice, alice_password):
    spa.require_consent = True
    uid, _ = await logged_in(client, authorize_params, alice, alice_password)
    await client.post(f"/interaction/{uid}/consent", json={"approve": True})
    _, next_time = await logged_in(client, authorize_params, alice, alice_password)  # a new login, the next day
    assert next_time["prompt"] is None

async def test_asking_for_more_scopes_asks_again(client, spa, authorize_params, alice, alice_password):
    spa.require_consent = True
    uid, _ = await logged_in(client, authorize_params, alice, alice_password, scope="openid")
    await client.post(f"/interaction/{uid}/consent", json={"approve": True})
    _, bigger = await logged_in(client, authorize_params, alice, alice_password, scope="openid svc:impots.read")
    assert bigger["prompt"] == "consent"  # svc:impots.read was never accepted

async def test_refusing_sends_access_denied_to_the_client(client, spa, authorize_params, alice, alice_password):
    spa.require_consent = True
    uid, _ = await logged_in(client, authorize_params, alice, alice_password)
    r = await client.post(f"/interaction/{uid}/consent", json={"approve": False})
    assert r.json()["redirect_to"] == "https://app.test/cb?error=access_denied&state=st4te"
    assert (await client.get(f"/interaction/{uid}")).status_code == 404  # this flow is over

async def test_consent_before_login_is_refused(client, spa, authorize_params):
    spa.require_consent = True
    r = await client.get("/authorize", params=authorize_params())
    uid = r.headers["location"].split("uid=")[1]
    r = await client.post(f"/interaction/{uid}/consent", json={"approve": True})
    assert r.status_code == 400
