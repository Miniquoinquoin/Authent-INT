"""/revoke (RFC 7009): a client revokes the family of its own refresh token; anything else changes nothing."""

from sqlalchemy import select

from authentint.infra.models.oauth import ClientType
from authentint.infra.models.oauth import OAuthClients
from authentint.infra.models.oauth import OAuthRefreshTokens


async def test_revoking_a_refresh_token_ends_its_family(client, s, wide_spa, offline_tokens, make_user, login_as):
    sso = await login_as(await make_user())
    first = await offline_tokens()
    second = (await client.post("/token", data={"grant_type": "refresh_token", "refresh_token": first["refresh_token"],
                                                "client_id": wide_spa.id})).json()

    r = await client.post("/revoke", data={"token": second["refresh_token"], "token_type_hint": "refresh_token", "client_id": wide_spa.id})
    assert r.status_code == 200
    assert r.content == b""

    family = (await s.scalars(select(OAuthRefreshTokens).where(OAuthRefreshTokens.session_id == sso.id)
                              .execution_options(populate_existing=True))).all()
    assert len(family) == 2 and all(t.revoked_at is not None for t in family)
    assert sorted(t.revocation_reason for t in family) == ["revoked_by_client", "revoked_by_client"]

    again = await client.post("/token", data={"grant_type": "refresh_token", "refresh_token": second["refresh_token"], "client_id": wide_spa.id})
    assert again.json() == {"error": "invalid_grant"}

async def test_an_unknown_token_is_a_200(client, wide_spa):
    r = await client.post("/revoke", data={"token": "never-issued", "client_id": wide_spa.id})
    assert r.status_code == 200  # §2.2: the client could do nothing with an error

async def test_an_access_token_is_a_200_but_stays_valid_until_exp(client, wide_spa, offline_tokens, make_user, login_as):
    await login_as(await make_user())
    tokens = await offline_tokens()

    r = await client.post("/revoke", data={"token": tokens["access_token"], "token_type_hint": "access_token", "client_id": wide_spa.id})
    assert r.status_code == 200
    assert (await client.get("/userinfo", headers={"Authorization": f"Bearer {tokens['access_token']}"})).status_code == 200

async def test_another_clients_token_is_refused_and_kept(client, s, wide_spa, offline_tokens, make_user, login_as):
    await login_as(await make_user())
    tokens = await offline_tokens()
    s.add(OAuthClients(id="other-spa", name="Other", type=ClientType.public, secret_hash=None, redirect_uris=[],
                       post_logout_redirect_uris=[], allowed_grants=["authorization_code"], allowed_scopes=[], require_consent=False))
    await s.flush()

    r = await client.post("/revoke", data={"token": tokens["refresh_token"], "client_id": "other-spa"})
    assert r.status_code == 400
    assert r.json() == {"error": "invalid_grant"}

    still = await client.post("/token", data={"grant_type": "refresh_token", "refresh_token": tokens["refresh_token"], "client_id": wide_spa.id})
    assert still.status_code == 200

async def test_an_unknown_client_is_an_invalid_client(client):
    r = await client.post("/revoke", data={"token": "x", "client_id": "nobody"})
    assert r.status_code == 400
    assert r.json() == {"error": "invalid_client"}

async def test_a_missing_token_is_an_invalid_request(client, wide_spa):
    r = await client.post("/revoke", data={"client_id": wide_spa.id})
    assert r.status_code == 400
    assert r.json() == {"error": "invalid_request"}
