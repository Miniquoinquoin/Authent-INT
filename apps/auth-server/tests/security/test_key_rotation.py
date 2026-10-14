"""
Key rotation is invisible to users (ADR §12, §15 "rotation de clé → les jetons émis avant
restent valides jusqu'à leur exp"): the retired key stays in the JWKS until the last token
it signed has expired, then leaves it. Resource servers verify against that JWKS.
"""

from datetime import UTC
from datetime import datetime
from datetime import timedelta

import pytest

from fastapi import HTTPException
from joserfc import jws
from sqlalchemy import select

from authentint.infra.models.identity import Role
from authentint.infra.models.keys import KeyStatus
from authentint.infra.models.keys import SigningKeys
from authentint.keys import keystore
from authentint.security.bearer import verify_access_token


def kid_of(token: str) -> str:
    return jws.extract_compact(token.encode()).headers()["kid"]

async def published(client) -> set[str]:
    return {k["kid"] for k in (await client.get("/.well-known/jwks.json")).json()["keys"]}


async def test_a_token_signed_before_a_rotation_stays_valid_until_its_key_expires(client, s, make_user, access_token):
    user, admin = await make_user(), await make_user(Role.admin)
    before = await access_token(user, "openid svc:impots.read")
    old_kid = kid_of(before)

    r = await client.post("/admin/keys/rotate", headers={"Authorization": f"Bearer {await access_token(admin, 'openid svc:admin.users')}"})
    assert r.status_code == 200

    # rotated: new tokens use another key, the old one is still published and still verifies
    after = await access_token(user, "openid svc:impots.read")
    assert kid_of(after) != old_kid
    assert old_kid in await published(client)
    assert (await verify_access_token(s, before))["sub"] == str(user.id)

    # the retired key's not_after (max token TTL after the rotation) has passed: gone from the JWKS
    retired = await s.scalar(select(SigningKeys).where(SigningKeys.kid == old_kid))
    assert retired.not_after < datetime.now(UTC) + timedelta(hours=1)  # bounded by the TTLs, not FAR_FUTURE
    retired.not_after = datetime.now(UTC) - timedelta(seconds=1)
    await s.flush()

    assert old_kid not in await published(client)
    with pytest.raises(HTTPException) as refused:
        await verify_access_token(s, before)
    assert refused.value.status_code == 401
    assert (await verify_access_token(s, after))["sub"] == str(user.id)  # the new key is unaffected

async def test_the_next_key_is_published_before_it_signs(client, s):
    # a resource server caching the JWKS already knows the key the next rotation will promote
    await keystore.ensure_active_key(s)
    next_kid = await s.scalar(select(SigningKeys.kid).where(SigningKeys.status == KeyStatus.next))
    assert next_kid in await published(client)
