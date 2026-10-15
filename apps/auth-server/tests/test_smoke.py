"""
Smoke spec (ADR §15): one whole flow, as a browser and an SPA would drive it, with no seam.
Login → code → tokens (nonce echoed, at_hash, stable sub, state round trip) → /userinfo →
refresh → logout, after which neither the refresh token nor the SSO session work any more.
"""

from urllib.parse import parse_qs
from urllib.parse import urlsplit

from joserfc import jwt
from joserfc.jwk import KeySet

from conftest import VERIFIER
from authentint.config import settings
from authentint.keys import keystore
from authentint.oidc.token import at_hash


async def test_login_tokens_refresh_logout(client, s, wide_spa, authorize_params, alice, alice_password):
    wide_spa.post_logout_redirect_uris = ["https://app.test/bye"]
    params = authorize_params(client_id=wide_spa.id, scope="openid offline_access svc:impots.read")
    keys = KeySet.import_key_set(await keystore.jwks(s))
    decode = lambda token: jwt.decode(token, keys, algorithms=["RS256"]).claims  # noqa: E731

    # no session yet: /authorize sends the browser to the login screen
    r = await client.get("/authorize", params=params)
    assert r.headers["location"].startswith(f"{settings.issuer}/login?uid=")
    uid = parse_qs(urlsplit(r.headers["location"]).query)["uid"][0]

    r = await client.post(f"/interaction/{uid}/login", json={"numero_fiscal": alice.numero_fiscal, "password": alice_password})
    assert r.status_code == 200 and r.json()["prompt"] is None
    resume = urlsplit(r.json()["redirect_to"])

    r = await client.get(f"{resume.path}?{resume.query}")  # now with the session cookie
    back = parse_qs(urlsplit(r.headers["location"]).query)
    assert back["state"] == ["st4te"]

    r = await client.post("/token", data={"grant_type": "authorization_code", "code": back["code"][0], "client_id": wide_spa.id,
                                          "redirect_uri": "https://app.test/cb", "code_verifier": VERIFIER})
    tokens = r.json()
    id_token = decode(tokens["id_token"])
    assert id_token["nonce"] == "n0nce" and id_token["aud"] == wide_spa.id and id_token["sub"] == str(alice.id)
    assert id_token["at_hash"] == at_hash(tokens["access_token"])
    assert "authentint" in decode(tokens["access_token"])["aud"]

    r = await client.get("/userinfo", headers={"Authorization": f"Bearer {tokens['access_token']}"})
    assert r.json()["sub"] == str(alice.id)

    r = await client.post("/token", data={"grant_type": "refresh_token", "refresh_token": tokens["refresh_token"], "client_id": wide_spa.id})
    refreshed = r.json()
    assert decode(refreshed["id_token"])["sub"] == str(alice.id)  # sub is stable

    r = await client.get("/end-session", params={"client_id": wide_spa.id, "post_logout_redirect_uri": "https://app.test/bye", "state": "s"})
    assert r.headers["location"] == "https://app.test/bye?state=s"

    r = await client.post("/token", data={"grant_type": "refresh_token", "refresh_token": refreshed["refresh_token"], "client_id": wide_spa.id})
    assert r.json() == {"error": "invalid_grant"}
    r = await client.get("/authorize", params=params)
    assert r.headers["location"].startswith(f"{settings.issuer}/login?uid=")  # no SSO left: log in again
