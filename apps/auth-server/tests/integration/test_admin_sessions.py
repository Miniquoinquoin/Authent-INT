"""/admin/sessions: every user's sessions, live only by default; an admin can close any of them (and its refresh tokens)."""

from uuid import uuid4

from sqlalchemy import select

from authentint.infra.models.audit import AuditEvents
from authentint.infra.models.audit import Sessions
from authentint.infra.models.identity import Role


def bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def test_list_live_by_default_and_filter_by_user(client, s, alice, make_user, login_as, access_token):
    admin = await make_user(Role.admin)
    h = bearer(await access_token(admin, "openid svc:admin.users"))
    live, closed = await login_as(alice), await login_as(alice)
    closed.revoked_at = closed.created_at
    await login_as(await make_user())
    await s.flush()

    r = await client.get("/admin/sessions", params={"user_id": str(alice.id)}, headers=h)
    assert r.status_code == 200 and r.json()["total"] == 1 and r.json()["items"][0]["id"] == str(live.id)

    r = await client.get("/admin/sessions", params={"user_id": str(alice.id), "include_closed": "true"}, headers=h)
    assert r.json()["total"] == 2

    r = await client.get("/admin/sessions", params={"user_id": str(alice.id), "include_closed": "true", "limit": 1, "offset": 1}, headers=h)
    assert len(r.json()["items"]) == 1 and r.json()["total"] == 2

async def test_an_admin_closes_a_session_and_its_refresh_tokens(client, s, alice, make_user, login_as, offline_tokens, access_token):
    admin = await make_user(Role.admin)
    sso = await login_as(alice)
    tokens = await offline_tokens()

    r = await client.delete(f"/admin/sessions/{sso.id}", headers=bearer(await access_token(admin, "openid svc:admin.users")))

    assert r.status_code == 204
    assert (await s.get(Sessions, sso.id, populate_existing=True)).revocation_reason == "revoked_by_admin"
    r = await client.post("/token", data={"grant_type": "refresh_token", "refresh_token": tokens["refresh_token"], "client_id": "wide-spa"})
    assert r.json() == {"error": "invalid_grant"}
    event = await s.scalar(select(AuditEvents).where(AuditEvents.event_type == "admin.session.revoked"))
    assert event.actor_user_id == admin.id and event.detail == {"target_session_id": str(sso.id), "target_user_id": str(alice.id)}

async def test_unknown_session_is_404(client, make_user, access_token):
    admin = await make_user(Role.admin)
    r = await client.delete(f"/admin/sessions/{uuid4()}", headers=bearer(await access_token(admin, "openid svc:admin.users")))
    assert r.status_code == 404

async def test_admin_sessions_needs_the_scope(client, alice, login_as, access_token):
    sso = await login_as(alice)
    token = await access_token(alice, "openid svc:impots.read")
    assert (await client.get("/admin/sessions", headers=bearer(token))).status_code == 403
    assert (await client.delete(f"/admin/sessions/{sso.id}", headers=bearer(token))).status_code == 403
