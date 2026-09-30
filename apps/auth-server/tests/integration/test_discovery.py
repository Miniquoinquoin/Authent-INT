"""What the Resource Servers (B3) read at startup: it must be exactly what B2 signs with."""

from sqlalchemy import update

from authentint.config import settings
from authentint.infra.models.keys import KeyStatus
from authentint.infra.models.keys import SigningKeys


async def test_discovery_matches_the_issuer(client):
    body = (await client.get("/.well-known/openid-configuration")).json()
    assert body["issuer"] == settings.issuer
    assert body["jwks_uri"] == f"{settings.issuer}/.well-known/jwks.json"
    assert body["code_challenge_methods_supported"] == ["S256"]
    assert "openid" in body["scopes_supported"]

async def test_jwks_publishes_only_public_rs256_keys(client):
    keys = (await client.get("/.well-known/jwks.json")).json()["keys"]
    assert keys
    for k in keys:
        assert k["kty"] == "RSA" and k["alg"] == "RS256" and k["kid"]
        assert "d" not in k  # the private exponent never leaves the server

async def test_liveness_needs_nothing(client):
    r = await client.get("/health/live")
    assert r.status_code == 200

async def test_ready_when_postgres_answers(client):
    r = await client.get("/health/ready")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}

async def test_not_ready_without_an_active_key(client, s):
    # retire every active key, inside the test's transaction: rolled back at the end
    await s.execute(update(SigningKeys).where(SigningKeys.status == KeyStatus.active).values(status=KeyStatus.retired))
    r = await client.get("/health/ready")
    assert r.status_code == 503
    assert r.json() == {"status": "unavailable", "reason": "no_active_key"}
