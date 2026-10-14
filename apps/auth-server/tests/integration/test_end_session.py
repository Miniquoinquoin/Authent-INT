"""/end-session: never redirects to an unregistered URI; with a session, ends it and every refresh token it issued."""

from urllib.parse import parse_qs
from urllib.parse import urlsplit

from sqlalchemy import select

from authentint.infra.models.audit import AuditEvents
from authentint.infra.models.oauth import OAuthRefreshTokens


LOGOUT_URI = "https://app.test/logged-out"


async def registered(s, wide_spa):
    wide_spa.post_logout_redirect_uris = [LOGOUT_URI]
    await s.flush()


async def test_logout_ends_the_session_and_its_refresh_tokens(client, s, wide_spa, offline_tokens, make_user, login_as):
    await registered(s, wide_spa)
    sso = await login_as(await make_user())
    tokens = await offline_tokens()

    r = await client.get("/end-session", params={"client_id": wide_spa.id, "post_logout_redirect_uri": LOGOUT_URI, "state": "bye"})

    assert r.status_code == 302
    location = urlsplit(r.headers["location"])
    assert f"{location.scheme}://{location.netloc}{location.path}" == LOGOUT_URI
    assert parse_qs(location.query) == {"state": ["bye"]}
    cookie = r.headers["set-cookie"]
    assert cookie.startswith('__Host-session=""') and "Max-Age=0" in cookie and "Secure" in cookie and "HttpOnly" in cookie

    await s.refresh(sso)
    assert sso.revocation_reason == "logout"
    rows = (await s.scalars(select(OAuthRefreshTokens).where(OAuthRefreshTokens.session_id == sso.id)
                            .execution_options(populate_existing=True))).all()
    assert rows and all(t.revocation_reason == "logout" for t in rows)
    assert await s.scalar(select(AuditEvents).where(AuditEvents.event_type == "logout", AuditEvents.actor_user_id == sso.user_id))

    refreshed = await client.post("/token", data={"grant_type": "refresh_token", "refresh_token": tokens["refresh_token"], "client_id": wide_spa.id})
    assert refreshed.json() == {"error": "invalid_grant"}

async def test_without_a_cookie_it_still_redirects(client, s, wide_spa):
    await registered(s, wide_spa)

    r = await client.get("/end-session", params={"client_id": wide_spa.id, "post_logout_redirect_uri": LOGOUT_URI})
    assert r.status_code == 302
    assert r.headers["location"] == LOGOUT_URI

async def test_a_garbage_cookie_is_just_cleared(client, s, wide_spa):
    await registered(s, wide_spa)
    client.cookies.set("__Host-session", "not-a-uuid")

    r = await client.get("/end-session", params={"client_id": wide_spa.id, "post_logout_redirect_uri": LOGOUT_URI})
    assert r.status_code == 302
    assert "Max-Age=0" in r.headers["set-cookie"]

async def test_an_unregistered_uri_never_redirects(client, s, wide_spa, make_user, login_as):
    await registered(s, wide_spa)
    sso = await login_as(await make_user())

    for uri in ("https://evil.test/", LOGOUT_URI + "/x", LOGOUT_URI.upper(), None):
        params = {"client_id": wide_spa.id, "post_logout_redirect_uri": uri}
        r = await client.get("/end-session", params={k: v for k, v in params.items() if v is not None})
        assert r.status_code == 400
        assert "location" not in r.headers

    await s.refresh(sso)
    assert sso.revoked_at is None  # an invalid request logs nobody out

async def test_an_unknown_client_never_redirects(client):
    r = await client.get("/end-session", params={"client_id": "nobody", "post_logout_redirect_uri": LOGOUT_URI})
    assert r.status_code == 400
    assert "location" not in r.headers
