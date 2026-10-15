"""
ADR §10 step 9: a live session is not consent. /authorize must not hand a code to a client
that requires consent just because the user is logged in, and the consent screen asks only
for what will be granted.
"""

from urllib.parse import parse_qs
from urllib.parse import urlsplit

from sqlalchemy import select

from authentint.config import settings
from authentint.infra.models.identity import Role
from authentint.infra.models.oauth import OAuthConsents


def uid_of(location: str) -> str:
    assert location.startswith(f"{settings.issuer}/login?uid="), location
    return parse_qs(urlsplit(location).query)["uid"][0]


async def test_a_session_alone_never_gets_a_code_from_a_consent_client(client, spa, authorize_params, make_user, login_as):
    spa.require_consent = True
    await login_as(await make_user())

    r = await client.get("/authorize", params=authorize_params())

    assert r.status_code == 302
    assert "code=" not in r.headers["location"]  # to the consent screen, never back to the client
    view = (await client.get(f"/interaction/{uid_of(r.headers['location'])}")).json()
    assert view["prompt"] == "consent"  # the user is known: no second login

async def test_once_accepted_the_same_request_gets_its_code(client, spa, authorize_params, make_user, login_as):
    spa.require_consent = True
    await login_as(await make_user())
    uid = uid_of((await client.get("/authorize", params=authorize_params())).headers["location"])

    done = (await client.post(f"/interaction/{uid}/consent", json={"approve": True})).json()
    r = await client.get(done["redirect_to"])

    assert r.status_code == 302
    assert r.headers["location"].startswith("https://app.test/cb?code=")

async def test_consent_asks_and_stores_only_what_the_role_allows(client, s, wide_spa, authorize_params, make_user, login_as):
    wide_spa.require_consent = True
    user = await make_user(Role.contribuable)
    await login_as(user)
    r = await client.get("/authorize", params=authorize_params(client_id=wide_spa.id, scope="openid svc:admin.users"))
    uid = uid_of(r.headers["location"])

    view = (await client.get(f"/interaction/{uid}")).json()
    assert view["scopes"] == ["openid"]  # svc:admin.users will never be granted: never asked

    await client.post(f"/interaction/{uid}/consent", json={"approve": True})
    [row] = await s.scalars(select(OAuthConsents).where(OAuthConsents.user_id == user.id))
    assert row.scopes == ["openid"]
