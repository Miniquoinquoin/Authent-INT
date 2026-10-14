"""/authorize → /token for authorization_code (ADR §10), with seam S1 standing in for the login step."""

from urllib.parse import parse_qs
from urllib.parse import urlsplit

from joserfc import jwt
from joserfc.jwk import KeySet
from sqlalchemy import select

from conftest import VERIFIER
from authentint.config import settings
from authentint.infra.models.oauth import OAuthRefreshTokens
from authentint.keys import keystore
from authentint.security.bearer import verify_access_token


async def authorize(client, authorize_params, **overrides) -> str:
    r = await client.get("/authorize", params=authorize_params(**overrides))
    assert r.status_code == 302
    return parse_qs(urlsplit(r.headers["location"]).query)["code"][0]

def form(code: str, client_id: str = "test-spa", **overrides) -> dict:
    return {"grant_type": "authorization_code", "code": code, "redirect_uri": "https://app.test/cb",
            "client_id": client_id, "code_verifier": VERIFIER, **overrides}


async def test_a_code_becomes_signed_tokens(client, s, authorize_params, make_user, login_as):
    user = await make_user()
    sso = await login_as(user)
    code = await authorize(client, authorize_params)

    r = await client.post("/token", data=form(code))

    assert r.status_code == 200
    assert r.headers["cache-control"] == "no-store"
    body = r.json()
    assert body["token_type"] == "Bearer"
    assert "refresh_token" not in body  # no offline_access requested

    access = await verify_access_token(s, body["access_token"])  # exactly what the Resource Servers will check
    assert access["sub"] == str(user.id)
    assert access["scope"] == "openid svc:impots.read"
    assert access["aud"] == ["authentint", "svc-impots"]

    keys = KeySet.import_key_set(await keystore.jwks(s))
    id_token = jwt.decode(body["id_token"], keys, algorithms=["RS256"]).claims
    assert id_token["iss"] == settings.issuer
    assert id_token["aud"] == "test-spa"
    assert id_token["sub"] == str(user.id)
    assert id_token["sid"] == str(sso.id)
    assert id_token["nonce"] == "n0nce"

    # signed, not encrypted: anyone holding a token reads it, so no personal identifier in it
    assert user.numero_fiscal not in str(access) + str(id_token)

async def test_the_verifier_must_match_the_challenge(client, authorize_params, make_user, login_as):
    await login_as(await make_user())
    code = await authorize(client, authorize_params)

    r = await client.post("/token", data=form(code, code_verifier="x" * 43))
    assert r.status_code == 400
    assert r.json() == {"error": "invalid_grant"}

async def test_the_redirect_uri_must_be_the_one_of_the_authorize_request(client, authorize_params, make_user, login_as):
    await login_as(await make_user())
    code = await authorize(client, authorize_params)

    r = await client.post("/token", data=form(code, redirect_uri="https://app.test/other"))
    assert r.status_code == 400
    assert r.json() == {"error": "invalid_grant"}

async def test_an_unknown_code_is_an_invalid_grant(client, spa):
    r = await client.post("/token", data=form("never-issued"))
    assert r.status_code == 400
    assert r.json() == {"error": "invalid_grant"}

async def test_a_replayed_code_revokes_what_it_issued(client, s, wide_spa, authorize_params, make_user, login_as):
    await login_as(await make_user())
    code = await authorize(client, authorize_params, client_id=wide_spa.id, scope="openid offline_access")

    first = await client.post("/token", data=form(code, client_id=wide_spa.id))
    assert first.status_code == 200
    assert "refresh_token" in first.json()

    replay = await client.post("/token", data=form(code, client_id=wide_spa.id))
    assert replay.status_code == 400
    assert replay.json() == {"error": "invalid_grant"}

    # ADR §10.3: a replayed code means it leaked, so what it produced is revoked
    refresh = (await s.scalars(select(OAuthRefreshTokens).where(OAuthRefreshTokens.client_id == wide_spa.id))).all()
    assert refresh and all(r.revoked_at is not None and r.revocation_reason == "code_replay" for r in refresh)
