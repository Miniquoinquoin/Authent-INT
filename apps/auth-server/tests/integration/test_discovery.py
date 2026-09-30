"""What the Resource Servers (B3) read at startup: it must be exactly what B2 signs with."""

from authentint.config import settings


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
