"""
Invariants 1 and 2 (architecture.md §15). An IdP that redirects to an unverified
redirect_uri hands the code, or the error, to the attacker: vulnerability n°1 of IdPs.
"""

import pytest


@pytest.mark.parametrize("redirect_uri", [
    "https://evil.example/cb",
    "https://app.test/cb/extra",      # prefix match is not a match
    "https://app.test/cb?next=evil",  # nor is a match "up to the query"
    "https://APP.test/cb",            # nor a case-insensitive one
])
async def test_unregistered_redirect_uri_never_redirects(client, authorize_params, redirect_uri):
    r = await client.get("/authorize", params=authorize_params(redirect_uri=redirect_uri))
    assert r.status_code == 400
    assert "location" not in r.headers

async def test_unknown_client_never_redirects(client, authorize_params):
    r = await client.get("/authorize", params=authorize_params(client_id="nobody"))
    assert r.status_code == 400
    assert "location" not in r.headers

@pytest.mark.parametrize("override", [
    {"code_challenge_method": "plain"},
    {"code_challenge_method": None},
    {"code_challenge": None},
    {"response_type": "token"},  # implicit flow
    {"scope": "svc:impots.read"},  # no openid
    {"nonce": None},
])
async def test_after_the_redirect_uri_check_errors_go_back_with_state(client, authorize_params, override):
    r = await client.get("/authorize", params=authorize_params(**override))
    assert r.status_code == 302
    assert r.headers["location"] == "https://app.test/cb?error=invalid_request&state=st4te"
