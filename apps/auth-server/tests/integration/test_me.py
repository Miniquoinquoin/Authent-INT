"""
GET /me and POST /me/password (ADR §9 "Self-service"). Only a token naming the IdP opens them;
the answer never carries the numero fiscal or a hash; a password change logs out every OTHER device.
"""

from sqlalchemy import select

from authentint.flows.login import ACCOUNT_LIMIT
from authentint.infra.models.audit import AuditEvents
from authentint.infra.models.audit import Sessions
from authentint.infra.models.identity import UserStatus
from authentint.security.passwords import verify_password


def bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def test_me_is_the_tokens_user_without_secrets(client, alice, access_token):
    r = await client.get("/me", headers=bearer(await access_token(alice, "openid")))

    assert r.status_code == 200
    assert r.json() == {"id": str(alice.id), "nom": "Martin", "prenom": "Alice", "email": "alice@example.test",
                        "role": "contribuable", "status": "active"}
    assert alice.numero_fiscal not in r.text and "hash" not in r.text

async def test_me_without_a_token_is_401(client):
    r = await client.get("/me")
    assert r.status_code == 401

async def test_me_with_a_garbage_token_is_401(client):
    r = await client.get("/me", headers=bearer("not.a.jwt"))
    assert r.status_code == 401 and r.headers["www-authenticate"] == 'Bearer error="invalid_token"'

async def test_me_refuses_a_service_only_token(client, alice, access_token):
    # no openid: aud is svc-impots alone, the IdP is not named (ADR §9 "Audience")
    r = await client.get("/me", headers=bearer(await access_token(alice, "svc:impots.read")))
    assert r.status_code == 401

async def test_me_refuses_a_disabled_account(client, s, alice, access_token):
    token = await access_token(alice, "openid")
    alice.status = UserStatus.disabled
    await s.flush()
    r = await client.get("/me", headers=bearer(token))
    assert r.status_code == 401


async def test_password_change_keeps_this_device_and_closes_the_others(client, s, alice, alice_password, login_as, access_token):
    here, elsewhere = await login_as(alice), await login_as(alice)
    token = await access_token(alice, "openid", sid=here.id)

    r = await client.post("/me/password", headers=bearer(token),
                          json={"current_password": alice_password, "new_password": "a-brand-new-passphrase"})

    assert r.status_code == 204
    await s.refresh(alice)
    assert await verify_password(alice.password_hash, "a-brand-new-passphrase")
    assert alice.password_changed_at is not None
    await s.refresh(here)
    await s.refresh(elsewhere)
    assert here.revoked_at is None
    assert elsewhere.revoked_at is not None and elsewhere.revocation_reason == "password_changed"
    event = await s.scalar(select(AuditEvents).where(AuditEvents.event_type == "password.changed"))
    assert event.actor_user_id == alice.id and event.session_id == here.id

async def test_password_change_revokes_the_other_devices_refresh_tokens(client, s, alice, alice_password, login_as, offline_tokens, access_token):
    other = await login_as(alice)
    tokens = await offline_tokens()  # issued under `other`
    here = await login_as(alice)

    await client.post("/me/password", headers=bearer(await access_token(alice, "openid", sid=here.id)),
                      json={"current_password": alice_password, "new_password": "a-brand-new-passphrase"})

    r = await client.post("/token", data={"grant_type": "refresh_token", "refresh_token": tokens["refresh_token"], "client_id": "wide-spa"})
    assert r.json() == {"error": "invalid_grant"}
    assert (await s.get(Sessions, other.id, populate_existing=True)).revoked_at is not None

async def test_wrong_current_password_is_401_and_audited(client, s, alice, login_as, access_token):
    r = await client.post("/me/password", headers=bearer(await access_token(alice, "openid", sid=(await login_as(alice)).id)),
                          json={"current_password": "wrong", "new_password": "a-brand-new-passphrase"})

    assert r.status_code == 401
    event = await s.scalar(select(AuditEvents).where(AuditEvents.event_type == "password.change_failed"))
    assert event.outcome.value == "failure" and event.actor_user_id == alice.id

async def test_guesses_through_me_password_are_rate_limited_per_account(client, alice, login_as, access_token):
    # a stolen access token is not a password oracle: same bucket as the login form
    token = await access_token(alice, "openid", sid=(await login_as(alice)).id)
    for _ in range(ACCOUNT_LIMIT):
        r = await client.post("/me/password", headers=bearer(token), json={"current_password": "wrong", "new_password": "a-brand-new-passphrase"})
        assert r.status_code == 401
    r = await client.post("/me/password", headers=bearer(token), json={"current_password": "wrong", "new_password": "a-brand-new-passphrase"})
    assert r.status_code == 429

async def test_the_new_password_follows_the_activation_length_rule(client, alice, alice_password, access_token):
    r = await client.post("/me/password", headers=bearer(await access_token(alice, "openid")),
                          json={"current_password": alice_password, "new_password": "short"})
    assert r.status_code == 422
