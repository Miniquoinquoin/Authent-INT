"""RFC 6749 §5.2: /token answers 400 {"error": ...}, never FastAPI's 422, and never echoes what it was sent."""

import pytest

from conftest import VERIFIER


async def test_an_empty_form_is_an_invalid_request(client):
    r = await client.post("/token", data={})
    assert r.status_code == 400
    assert r.json() == {"error": "invalid_request"}
    assert r.headers["cache-control"] == "no-store"

@pytest.mark.parametrize("grant_type", ["password", "client_credentials", "implicit"])
async def test_an_unknown_grant_is_unsupported(client, grant_type):
    r = await client.post("/token", data={"grant_type": grant_type, "code": "x", "redirect_uri": "https://app.test/cb",
                                          "client_id": "test-spa", "code_verifier": VERIFIER})
    assert r.status_code == 400
    assert r.json() == {"error": "unsupported_grant_type"}

async def test_the_submitted_secrets_are_never_echoed(client):
    # code_verifier too short → validation error; FastAPI's default 422 would echo every input
    r = await client.post("/token", data={"grant_type": "authorization_code", "code": "SECRET-CODE-VALUE",
                                          "redirect_uri": "https://app.test/cb", "client_id": "test-spa",
                                          "code_verifier": "SECRET-VERIFIER"})
    assert r.status_code == 400
    assert "SECRET" not in r.text
