"""POST /admin/keys/rotate (ADR §12): next → active → retired, and the rotation is audited in the same transaction."""

from joserfc import jws
from joserfc.jwk import RSAKey
from sqlalchemy import func
from sqlalchemy import select

from authentint.infra.models.audit import AuditEvents
from authentint.infra.models.identity import Role
from authentint.infra.models.keys import KeyStatus
from authentint.infra.models.keys import SigningKeys
from authentint.keys import keystore


async def kid(s, status: KeyStatus) -> str:
    return await s.scalar(select(SigningKeys.kid).where(SigningKeys.status == status))


async def test_rotation_promotes_next_and_is_audited(client, s, make_user, access_token):
    admin = await make_user(Role.admin)
    token = await access_token(admin, "openid svc:admin.users")
    old_active, old_next = await kid(s, KeyStatus.active), await kid(s, KeyStatus.next)

    r = await client.post("/admin/keys/rotate", headers={"Authorization": f"Bearer {token}"})

    assert r.status_code == 200
    assert await kid(s, KeyStatus.active) == old_next  # already published for a full cycle
    assert await s.scalar(select(SigningKeys.status).where(SigningKeys.kid == old_active)) == KeyStatus.retired
    assert await kid(s, KeyStatus.next) not in (old_active, old_next)
    audited = await s.scalar(select(func.count()).select_from(AuditEvents)
                             .where(AuditEvents.event_type == "keys.rotated", AuditEvents.actor_user_id == admin.id))
    assert audited == 1

async def test_rotation_needs_the_admin_scope(client, s, make_user, access_token):
    agent = await make_user(Role.agent)
    token = await access_token(agent, "openid svc:impots.read")
    await keystore.ensure_active_key(s)
    before = await kid(s, KeyStatus.active)

    r = await client.post("/admin/keys/rotate", headers={"Authorization": f"Bearer {token}"})

    assert r.status_code == 403
    assert await kid(s, KeyStatus.active) == before

async def test_rotation_needs_a_token(client):
    r = await client.post("/admin/keys/rotate")
    assert r.status_code in (401, 403)  # HTTPBearer: no credentials at all

async def test_active_key_signs_and_follows_a_rotation(s):
    # keystore._private_key is cached per kid (perf, docs/load-report.md): the cache must never
    # hand out the previous key after a rotation, and what it returns must really sign
    await keystore.ensure_active_key(s)
    key = await keystore.active(s)
    public = RSAKey.import_key(await s.scalar(select(SigningKeys.public_jwk).where(SigningKeys.kid == key.kid)))
    token = jws.serialize_compact({"alg": "RS256", "kid": key.kid}, b"payload", key)
    assert jws.deserialize_compact(token, public).payload == b"payload"
    assert await keystore.active(s) is key  # second call: cache hit, no decrypt + import

    next_kid = await kid(s, KeyStatus.next)
    await keystore.rotate(s)

    assert (await keystore.active(s)).kid == next_kid
