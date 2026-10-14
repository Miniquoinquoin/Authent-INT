"""
/me/sessions (ADR §9 "plusieurs appareils"). A user sees and closes their own devices only:
someone else's session answers 404 like an unknown id (IDOR), and closing one kills its refresh tokens.
"""

from uuid import uuid4

from sqlalchemy import select

from authentint.config import settings
from authentint.infra.models.audit import AuditEvents
from authentint.infra.models.audit import Sessions


def bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def test_lists_live_sessions_and_marks_the_current_one(client, s, alice, make_user, login_as, access_token):
    here, other = await login_as(alice), await login_as(alice)
    closed = await login_as(alice)
    closed.revoked_at = closed.created_at
    await login_as(await make_user())  # someone else's: never listed
    await s.flush()

    r = await client.get("/me/sessions", headers=bearer(await access_token(alice, "openid", sid=here.id)))

    assert r.status_code == 200
    listed = {item["id"]: item["current"] for item in r.json()}
    assert listed == {str(here.id): True, str(other.id): False}
    assert r.json()[0].keys() == {"id", "device_label", "ip_address", "created_at", "last_seen_at", "expires_at", "current"}

async def test_closing_my_session_revokes_it_and_its_refresh_tokens(client, s, alice, login_as, offline_tokens, access_token):
    phone = await login_as(alice)
    tokens = await offline_tokens()

    r = await client.delete(f"/me/sessions/{phone.id}", headers=bearer(await access_token(alice, "openid")))

    assert r.status_code == 204
    phone = await s.get(Sessions, phone.id, populate_existing=True)
    assert phone.revoked_at is not None and phone.revocation_reason == "revoked_by_user"
    r = await client.post("/token", data={"grant_type": "refresh_token", "refresh_token": tokens["refresh_token"], "client_id": "wide-spa"})
    assert r.json() == {"error": "invalid_grant"}
    event = await s.scalar(select(AuditEvents).where(AuditEvents.event_type == "session.revoked"))
    assert event.actor_user_id == alice.id and event.session_id == phone.id

async def test_someone_elses_session_is_404_like_an_unknown_one(client, s, alice, make_user, login_as, access_token):
    victim = await login_as(await make_user())
    token = await access_token(alice, "openid")

    theirs = await client.delete(f"/me/sessions/{victim.id}", headers=bearer(token))
    unknown = await client.delete(f"/me/sessions/{uuid4()}", headers=bearer(token))

    assert theirs.status_code == unknown.status_code == 404
    assert theirs.json() == unknown.json()
    assert (await s.get(Sessions, victim.id, populate_existing=True)).revoked_at is None

async def test_sessions_need_an_idp_token(client, alice, access_token):
    assert (await client.get("/me/sessions")).status_code == 401
    r = await client.get("/me/sessions", headers=bearer(await access_token(alice, "svc:impots.read")))
    assert r.status_code == 401
    r = await client.delete(f"/me/sessions/{uuid4()}", headers=bearer(await access_token(alice, "svc:impots.read")))
    assert r.status_code == 401

async def test_the_spa_may_send_delete_cross_origin(client):
    # CORS preflight from app. to auth.: without DELETE allowed, the browser never sends the request
    r = await client.options("/me/sessions/x", headers={"Origin": settings.public_base_url, "Access-Control-Request-Method": "DELETE",
                                                         "Access-Control-Request-Headers": "authorization"})
    assert r.status_code == 200 and "DELETE" in r.headers["access-control-allow-methods"]
