"""/authorize without a session → interaction → the frontend asks what's next (ADR §9, §10 steps 6-8)."""

from urllib.parse import parse_qs
from urllib.parse import urlsplit

from uuid import UUID

from authentint.config import settings
from authentint.infra.models.audit import Sessions


async def start(client, authorize_params) -> str:
    r = await client.get("/authorize", params=authorize_params())
    assert r.status_code == 302
    location = urlsplit(r.headers["location"])
    assert f"{location.scheme}://{location.netloc}{location.path}" == f"{settings.issuer}/login"
    return parse_qs(location.query)["uid"][0]

async def test_no_session_leads_to_the_login_step(client, authorize_params):
    uid = await start(client, authorize_params)
    r = await client.get(f"/interaction/{uid}")
    assert r.status_code == 200
    assert r.json() == {"prompt": "login", "client_name": "Test SPA", "scopes": ["openid", "svc:impots.read"], "redirect_to": None}

async def test_the_uid_is_the_only_thing_the_browser_carries(client, authorize_params):
    uid = await start(client, authorize_params)
    body = (await client.get(f"/interaction/{uid}")).json()
    # client_id, redirect_uri, state, code_challenge stay server side: nothing to tamper with
    assert "https://app.test/cb" not in str(body) and "st4te" not in str(body)

async def test_unknown_uid_is_404(client):
    r = await client.get("/interaction/does-not-exist")
    assert r.status_code == 404

async def test_right_credentials_finish_the_interaction(client, authorize_params, alice, alice_password):
    uid = await start(client, authorize_params)
    r = await client.post(f"/interaction/{uid}/login", json={"numero_fiscal": alice.numero_fiscal, "password": alice_password})
    assert r.status_code == 200
    body = r.json()
    assert body["prompt"] is None  # test-spa requires no consent: nothing left to ask
    assert body["redirect_to"].startswith(f"{settings.issuer}/authorize?")

async def test_login_sets_the_session_cookie(client, s, authorize_params, alice, alice_password):
    uid = await start(client, authorize_params)
    r = await client.post(f"/interaction/{uid}/login", json={"numero_fiscal": alice.numero_fiscal, "password": alice_password})
    cookie = r.headers["set-cookie"]
    name, value = cookie.split(";")[0].split("=", 1)
    assert name == "__Host-session"
    stored = await s.get(Sessions, UUID(value))  # the cookie carries the id of a real session...
    assert stored.user_id == alice.id            # ...that belongs to alice

async def test_the_session_cookie_is_locked_down(client, authorize_params, alice, alice_password):
    uid = await start(client, authorize_params)
    r = await client.post(f"/interaction/{uid}/login", json={"numero_fiscal": alice.numero_fiscal, "password": alice_password})
    attributes = [a.strip().lower() for a in r.headers["set-cookie"].split(";")[1:]]
    assert "httponly" in attributes      # JavaScript cannot read it: an XSS cannot steal the session
    assert "secure" in attributes        # only sent over HTTPS
    assert "samesite=lax" in attributes  # not sent by cross-site POSTs: blocks CSRF
    assert "path=/" in attributes        # required by the __Host- prefix
    assert not any(a.startswith("domain") for a in attributes)  # __Host-: never shared with sub-domains

async def test_wrong_credentials_are_401_without_cookie(client, authorize_params, alice):
    uid = await start(client, authorize_params)
    r = await client.post(f"/interaction/{uid}/login", json={"numero_fiscal": alice.numero_fiscal, "password": "wrong"})
    assert r.status_code == 401
    assert "set-cookie" not in r.headers

async def test_login_rejects_a_malformed_numero_fiscal(client, authorize_params):
    uid = await start(client, authorize_params)
    r = await client.post(f"/interaction/{uid}/login", json={"numero_fiscal": "not-a-number", "password": "x"})
    assert r.status_code == 422
