"""
ADR §7: granted = requested ∩ allowed(role) ∩ client.allowed_scopes, computed by /authorize.
Without it, a contribuable asking for svc:admin.users got it signed into the access token.
"""

from urllib.parse import parse_qs
from urllib.parse import urlsplit

from sqlalchemy import func
from sqlalchemy import select

from authentint.infra.models.audit import AuditEvents
from authentint.infra.models.identity import Role
from authentint.infra.models.identity import UserStatus
from authentint.infra.models.oauth import OAuthAuthorizationCodes
from authentint.security.passwords import hash_token


async def code_row(s, location: str) -> OAuthAuthorizationCodes:
    code = parse_qs(urlsplit(location).query)["code"][0]
    return await s.get(OAuthAuthorizationCodes, hash_token(code))

async def reductions(s) -> int:
    return await s.scalar(select(func.count()).select_from(AuditEvents).where(AuditEvents.event_type == "authorize.scope_reduced"))


async def test_a_contribuable_cannot_obtain_admin_scopes(client, s, wide_spa, authorize_params, make_user, login_as):
    await login_as(await make_user(Role.contribuable))
    before = await reductions(s)

    r = await client.get("/authorize", params=authorize_params(client_id=wide_spa.id, scope="openid svc:admin.users"))

    assert r.status_code == 302
    row = await code_row(s, r.headers["location"])
    assert row.scope == "openid"
    assert await reductions(s) == before + 1  # ADR §7: every reduction is audited

async def test_nothing_is_reduced_when_the_role_allows_it(client, s, wide_spa, authorize_params, make_user, login_as):
    await login_as(await make_user(Role.agent))
    before = await reductions(s)

    r = await client.get("/authorize", params=authorize_params(client_id=wide_spa.id, scope="openid svc:impots.read"))

    row = await code_row(s, r.headers["location"])
    assert row.scope == "openid svc:impots.read"
    assert await reductions(s) == before

async def test_a_locked_user_with_a_live_session_gets_no_code(client, s, authorize_params, make_user, login_as):
    await login_as(await make_user(status=UserStatus.locked))

    r = await client.get("/authorize", params=authorize_params())

    assert r.status_code == 302
    assert r.headers["location"] == "https://app.test/cb?error=access_denied&state=st4te"
