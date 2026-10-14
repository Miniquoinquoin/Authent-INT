"""
Security regression tests of the Resource Server (ADR §11 table, ADR §15, invariants 6 and 12).
One rule per test. A protected route on a bare app keeps them independent of the business routes.
"""

import base64
import hashlib
import hmac
import json
import time
from typing import Annotated

import pytest
from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient

from mockservices.auth import Verifier, require_scope
from mockservices.config import Settings

from conftest import ISSUER


@pytest.fixture
async def client(jwks):
    settings = Settings(service_name="svc-impots", issuer=ISSUER, audience="svc-impots")
    app = FastAPI()
    app.state.settings = settings
    app.state.verifier = Verifier(settings, jwks)

    @app.get("/protected")
    async def protected(claims: Annotated[dict, Depends(require_scope("svc:impots.read"))]):
        return {"sub": claims["sub"]}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://impots.authentint.local") as c:
        yield c


async def call(client: AsyncClient, token: str):
    return await client.get("/protected", headers={"Authorization": f"Bearer {token}"})


def b64(data: bytes | dict) -> str:
    if isinstance(data, dict):
        data = json.dumps(data).encode()
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def claims_of(token: str) -> dict:
    payload = token.split(".")[1]
    return json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))


def assert_invalid_token(response):
    assert response.status_code == 401
    assert 'error="invalid_token"' in response.headers["WWW-Authenticate"]
    assert response.json() == {"detail": "invalid_token"}  # the reason stays in the logs


# --- the happy path ------------------------------------------------------------------------

async def test_a_valid_token_with_the_right_scope_is_accepted(client, issuer):
    response = await call(client, issuer.token())

    assert response.status_code == 200
    assert response.json() == {"sub": "00000000-0000-0000-0000-00000000002a"}


async def test_a_token_for_several_services_is_accepted_by_each_of_them(client, issuer):
    response = await call(client, issuer.token(aud=["svc-cadastre", "svc-impots"]))

    assert response.status_code == 200


# --- 401: who are you? ---------------------------------------------------------------------

async def test_no_token_is_401_with_a_bare_bearer_challenge(client):
    response = await client.get("/protected")

    assert response.status_code == 401
    # RFC 6750 §3.1: no credentials at all, so no error code
    assert response.headers["WWW-Authenticate"] == 'Bearer realm="svc-impots"'


async def test_another_authorization_scheme_is_401(client, issuer):
    response = await client.get("/protected", headers={"Authorization": f"Basic {issuer.token()}"})

    assert response.status_code == 401


async def test_garbage_instead_of_a_jwt_is_401(client):
    assert_invalid_token(await call(client, "not.a.jwt"))


async def test_an_expired_token_is_401(client, issuer):
    past = int(time.time()) - 3600
    assert_invalid_token(await call(client, issuer.token(iat=past - 600, exp=past)))


async def test_a_token_without_exp_is_401(client, issuer):
    assert_invalid_token(await call(client, issuer.token(exp=None)))


async def test_a_token_issued_in_the_future_is_401(client, issuer):
    assert_invalid_token(await call(client, issuer.token(iat=int(time.time()) + 3600)))


async def test_a_token_not_yet_valid_is_401(client, issuer):
    assert_invalid_token(await call(client, issuer.token(nbf=int(time.time()) + 3600)))


async def test_a_token_from_another_issuer_is_401(client, issuer):
    assert_invalid_token(await call(client, issuer.token(iss="https://evil.example")))


async def test_a_token_for_svc_cadastre_replayed_on_svc_impots_is_401(client, issuer):
    assert_invalid_token(await call(client, issuer.token(aud=["svc-cadastre"], scope="svc:impots.read")))


async def test_a_token_without_aud_is_401(client, issuer):
    assert_invalid_token(await call(client, issuer.token(aud=None)))


async def test_an_id_token_is_not_an_access_token(client, issuer):
    # Same issuer, same key: only typ tells an ID token (typ JWT) from an access token (RFC 9068)
    assert_invalid_token(await call(client, issuer.token(header={"typ": "JWT"})))


async def test_alg_none_is_401(client, issuer):
    header = {"alg": "none", "typ": "at+jwt", "kid": "kid-1"}
    forged = f"{b64(header)}.{b64(claims_of(issuer.token()))}."

    assert_invalid_token(await call(client, forged))


async def test_hs256_signed_with_the_public_key_as_hmac_secret_is_401(client, issuer):
    # The key confusion attack: the public key is public, so if the token chose the algorithm,
    # anyone could sign with it as an HMAC secret
    secret = issuer.active.as_pem(private=False)
    signing_input = f"{b64({'alg': 'HS256', 'typ': 'at+jwt', 'kid': 'kid-1'})}.{b64(claims_of(issuer.token()))}"
    signature = hmac.new(secret, signing_input.encode(), hashlib.sha256).digest()

    assert_invalid_token(await call(client, f"{signing_input}.{b64(signature)}"))


async def test_a_tampered_payload_is_401(client, issuer):
    header, _, signature = issuer.token().split(".")
    widened = b64(claims_of(issuer.token()) | {"scope": "svc:impots.read svc:impots.write"})

    assert_invalid_token(await call(client, f"{header}.{widened}.{signature}"))


async def test_a_token_signed_by_a_key_the_issuer_never_published_is_401(client, issuer):
    forged = issuer.token(key=issuer.pool["attacker"], header={"kid": "kid-1"})

    assert_invalid_token(await call(client, forged))


async def test_a_token_with_an_unknown_kid_is_401(client, issuer):
    assert_invalid_token(await call(client, issuer.token(key=issuer.pool["attacker"])))


async def test_tokens_are_503_until_the_issuer_has_been_reached_once(client, issuer):
    issuer.down = True

    response = await call(client, issuer.token())

    assert response.status_code == 503


# --- 403: we know who you are, you can't do this here ----------------------------------------

async def test_a_valid_token_without_the_scope_is_403_insufficient_scope(client, issuer):
    response = await call(client, issuer.token(scope="openid svc:cadastre.read"))

    assert response.status_code == 403
    assert response.headers["WWW-Authenticate"] == (
        'Bearer realm="svc-impots", error="insufficient_scope", scope="svc:impots.read"'
    )


async def test_a_scope_is_matched_whole_not_as_a_prefix(client, issuer):
    response = await call(client, issuer.token(scope="svc:impots.readonly"))

    assert response.status_code == 403
