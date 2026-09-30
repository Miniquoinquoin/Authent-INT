"""/authorize without a session → interaction → the frontend asks what's next (ADR §9, §10 steps 6-8)."""

from urllib.parse import parse_qs
from urllib.parse import urlsplit

from authentint.config import settings


async def start(client, authorize_params) -> str:
    r = await client.get("/authorize", params=authorize_params())
    assert r.status_code == 302
    location = urlsplit(r.headers["location"])
    assert f"{location.scheme}://{location.netloc}{location.path}" == f"{settings.public_base_url}/login"
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

async def test_login_contract_is_published_but_not_built(client, authorize_params):
    uid = await start(client, authorize_params)
    r = await client.post(f"/interaction/{uid}/login", json={"numero_fiscal": "1801234567890", "password": "x"})
    assert r.status_code == 501  # B1 replaces this test with the real ones

async def test_login_rejects_a_malformed_numero_fiscal(client, authorize_params):
    uid = await start(client, authorize_params)
    r = await client.post(f"/interaction/{uid}/login", json={"numero_fiscal": "not-a-number", "password": "x"})
    assert r.status_code == 422
