"""
/admin/clients (ADR §9 "Admin"). Redirect URIs are registered exactly (absolute, no wildcard, no
fragment); a confidential client's secret is shown once and stored only as an Argon2 hash; a client
that ever got a refresh token can't be deleted (409), only restricted.
"""

from sqlalchemy import select

from authentint.infra.models.audit import AuditEvents
from authentint.infra.models.identity import Role
from authentint.infra.models.oauth import OAuthClients
from authentint.security.passwords import verify_password


def bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}

async def admin_headers(make_user, access_token) -> dict:
    return bearer(await access_token(await make_user(Role.admin), "openid svc:admin.users"))

def new_client(**overrides) -> dict:
    body = {"id": "svc-test", "name": "Service de test", "type": "confidential", "redirect_uris": ["https://svc.test/cb"],
            "allowed_grants": ["authorization_code"], "allowed_scopes": ["openid"]}
    return {**body, **overrides}


async def test_confidential_secret_is_shown_once_and_stored_hashed(client, s, make_user, access_token):
    h = await admin_headers(make_user, access_token)

    r = await client.post("/admin/clients", json=new_client(), headers=h)

    assert r.status_code == 201
    secret = r.json()["client_secret"]
    stored = await s.get(OAuthClients, "svc-test")
    assert stored.secret_hash != secret and await verify_password(stored.secret_hash, secret)
    again = await client.get("/admin/clients/svc-test", headers=h)
    assert "client_secret" not in again.json() and "secret_hash" not in again.json()
    event = await s.scalar(select(AuditEvents).where(AuditEvents.event_type == "admin.client.created"))
    assert event.detail == {"target_client_id": "svc-test"} and event.client_id == "svc-test"

async def test_public_client_gets_no_secret(client, make_user, access_token):
    r = await client.post("/admin/clients", json=new_client(type="public"), headers=await admin_headers(make_user, access_token))
    assert r.status_code == 201 and r.json()["client_secret"] is None

async def test_taken_id_is_409(client, spa, make_user, access_token):
    r = await client.post("/admin/clients", json=new_client(id=spa.id), headers=await admin_headers(make_user, access_token))
    assert r.status_code == 409

async def test_redirect_uris_must_be_exact(client, make_user, access_token):
    h = await admin_headers(make_user, access_token)
    for uri in ("/relative", "https://*.svc.test/cb", "https://svc.test/cb#frag", "http://svc.test/cb", "javascript:alert(1)"):
        r = await client.post("/admin/clients", json=new_client(redirect_uris=[uri]), headers=h)
        assert r.status_code == 422, uri
    r = await client.post("/admin/clients", json=new_client(redirect_uris=["http://localhost:5173/cb"]), headers=h)
    assert r.status_code == 201

async def test_list_and_patch(client, spa, make_user, access_token):
    h = await admin_headers(make_user, access_token)

    assert spa.id in [c["id"] for c in (await client.get("/admin/clients", headers=h)).json()]
    r = await client.patch(f"/admin/clients/{spa.id}", json={"name": "Renamed", "require_consent": True}, headers=h)
    assert r.status_code == 200 and r.json()["name"] == "Renamed" and r.json()["require_consent"] is True
    assert (await client.patch(f"/admin/clients/{spa.id}", json={"redirect_uris": ["https://x.test/*"]}, headers=h)).status_code == 422
    assert (await client.patch("/admin/clients/nobody", json={"name": "x"}, headers=h)).status_code == 404

async def test_delete_an_unused_client(client, s, make_user, access_token):
    h = await admin_headers(make_user, access_token)
    await client.post("/admin/clients", json=new_client(), headers=h)

    assert (await client.delete("/admin/clients/svc-test", headers=h)).status_code == 204
    assert (await client.get("/admin/clients/svc-test", headers=h)).status_code == 404

async def test_a_client_with_refresh_tokens_cannot_be_deleted(client, s, alice, login_as, offline_tokens, make_user, access_token):
    await login_as(alice)
    await offline_tokens()  # wide-spa now has a refresh token

    r = await client.delete("/admin/clients/wide-spa", headers=await admin_headers(make_user, access_token))

    assert r.status_code == 409
    assert await s.get(OAuthClients, "wide-spa") is not None

async def test_admin_clients_needs_the_scope(client, make_user, access_token):
    agent = await make_user(Role.agent)
    assert (await client.get("/admin/clients")).status_code == 401
    r = await client.post("/admin/clients", json=new_client(), headers=bearer(await access_token(agent, "openid svc:impots.read")))
    assert r.status_code == 403
