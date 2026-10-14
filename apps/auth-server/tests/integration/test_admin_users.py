"""
/admin/users (ADR §9 "Admin"), behind svc:admin.users. Accounts are disabled, never deleted (ADR §6);
locking or disabling logs the user out everywhere; an admin can't demote, lock or disable themselves;
every change is audited with the admin as actor and the target in detail.
"""

from uuid import uuid4

from datetime import UTC
from datetime import datetime
from datetime import timedelta

from sqlalchemy import select

from authentint.infra.models.audit import AuditEvents
from authentint.infra.models.audit import Sessions
from authentint.infra.models.identity import ActivationTokens
from authentint.infra.models.identity import Role
from authentint.infra.models.identity import User
from authentint.infra.models.identity import UserStatus


def bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}

async def admin_headers(make_user, access_token) -> tuple[User, dict]:
    admin = await make_user(Role.admin)
    return admin, bearer(await access_token(admin, "openid svc:admin.users"))

async def audited(s, event_type: str, admin: User, target: User) -> bool:
    event = await s.scalar(select(AuditEvents).where(AuditEvents.event_type == event_type).order_by(AuditEvents.id.desc()))
    return event is not None and event.actor_user_id == admin.id and event.detail["target_user_id"] == str(target.id)


async def test_list_filters_and_counts(client, alice, make_user, access_token):
    _, h = await admin_headers(make_user, access_token)

    r = await client.get("/admin/users", params={"q": "alice@example", "role": "contribuable", "status": "active"}, headers=h)

    assert r.status_code == 200
    assert r.json()["total"] == 1 and [u["id"] for u in r.json()["items"]] == [str(alice.id)]
    assert "numero_fiscal_hmac" not in r.json()["items"][0] and "password_hash" not in r.json()["items"][0]

async def test_list_pages_with_limit_and_offset(client, make_user, access_token):
    _, h = await admin_headers(make_user, access_token)
    for _ in range(3):
        await make_user(Role.agent)

    first = (await client.get("/admin/users", params={"role": "agent", "limit": 2}, headers=h)).json()
    rest = (await client.get("/admin/users", params={"role": "agent", "limit": 2, "offset": 2}, headers=h)).json()

    assert first["total"] == rest["total"] >= 3
    assert not {u["id"] for u in first["items"]} & {u["id"] for u in rest["items"]}

async def test_get_one_or_404(client, alice, make_user, access_token):
    _, h = await admin_headers(make_user, access_token)
    assert (await client.get(f"/admin/users/{alice.id}", headers=h)).json()["email"] == alice.email
    assert (await client.get(f"/admin/users/{uuid4()}", headers=h)).status_code == 404

async def test_patch_role_and_status_is_audited(client, s, alice, make_user, access_token):
    admin, h = await admin_headers(make_user, access_token)

    r = await client.patch(f"/admin/users/{alice.id}", json={"role": "agent"}, headers=h)

    assert r.status_code == 200 and r.json()["role"] == "agent"
    assert await audited(s, "admin.user.updated", admin, alice)
    assert (await client.patch(f"/admin/users/{alice.id}", json={"status": "nope"}, headers=h)).status_code == 422

async def test_an_admin_cannot_demote_or_disable_themselves(client, make_user, access_token):
    admin, h = await admin_headers(make_user, access_token)

    assert (await client.patch(f"/admin/users/{admin.id}", json={"role": "agent"}, headers=h)).status_code == 409
    assert (await client.patch(f"/admin/users/{admin.id}", json={"status": "disabled"}, headers=h)).status_code == 409
    assert (await client.delete(f"/admin/users/{admin.id}", headers=h)).status_code == 409
    assert (await client.post(f"/admin/users/{admin.id}/lock", headers=h)).status_code == 409

async def test_delete_disables_and_logs_out(client, s, alice, make_user, login_as, access_token):
    admin, h = await admin_headers(make_user, access_token)
    sso = await login_as(alice)

    r = await client.delete(f"/admin/users/{alice.id}", headers=h)

    assert r.status_code == 204
    assert (await s.get(User, alice.id, populate_existing=True)).status == UserStatus.disabled  # still there: never hard-deleted
    assert (await s.get(Sessions, sso.id, populate_existing=True)).revoked_at is not None
    assert await audited(s, "admin.user.disabled", admin, alice)

async def test_lock_then_unlock(client, s, alice, make_user, login_as, access_token):
    admin, h = await admin_headers(make_user, access_token)
    sso = await login_as(alice)

    r = await client.post(f"/admin/users/{alice.id}/lock", headers=h)
    assert r.status_code == 200 and r.json()["status"] == "locked"
    assert (await s.get(Sessions, sso.id, populate_existing=True)).revocation_reason == "locked_by_admin"

    alice.failed_login_count, alice.locked_until = 3, datetime.now(UTC) + timedelta(minutes=5)
    await s.flush()
    r = await client.post(f"/admin/users/{alice.id}/unlock", headers=h)
    assert r.json()["status"] == "active" and r.json()["failed_login_count"] == 0 and r.json()["locked_until"] is None
    assert await audited(s, "admin.user.unlocked", admin, alice)

async def test_unlock_does_not_reactivate_a_disabled_account(client, s, alice, make_user, access_token):
    _, h = await admin_headers(make_user, access_token)
    alice.status = UserStatus.disabled
    await s.flush()
    assert (await client.post(f"/admin/users/{alice.id}/unlock", headers=h)).json()["status"] == "disabled"

async def test_resend_activation_mails_a_new_link(client, s, bob, alice, mailbox, make_user, access_token):
    admin, h = await admin_headers(make_user, access_token)

    r = await client.post(f"/admin/users/{bob.id}/resend-activation", headers=h)

    assert r.status_code == 202
    assert [m["to"] for m in mailbox.sent] == [bob.email] and "/activate?token=" in mailbox.sent[0]["body"]
    assert await s.scalar(select(ActivationTokens).where(ActivationTokens.user_id == bob.id)) is not None
    assert await audited(s, "admin.user.activation_resent", admin, bob)
    assert (await client.post(f"/admin/users/{alice.id}/resend-activation", headers=h)).status_code == 409  # already active

async def test_admin_users_needs_the_scope(client, alice, make_user, access_token):
    assert (await client.get("/admin/users")).status_code == 401
    agent = await make_user(Role.agent)
    r = await client.get("/admin/users", headers=bearer(await access_token(agent, "openid svc:impots.read")))
    assert r.status_code == 403
    r = await client.delete(f"/admin/users/{alice.id}", headers=bearer(await access_token(agent, "openid svc:admin.audit")))
    assert r.status_code == 403
