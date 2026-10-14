"""
grant_type=refresh_token (RFC 6749 §6, ADR §10): every refresh rotates the token, and a token
presented twice revokes its whole family and the session it came from.
"""

from datetime import UTC
from datetime import datetime

from joserfc import jwt
from joserfc.jwk import KeySet
from sqlalchemy import select
from sqlalchemy import update

from authentint.infra.models.audit import AuditEvents
from authentint.infra.models.audit import Sessions
from authentint.infra.models.oauth import ClientType
from authentint.infra.models.oauth import OAuthClients
from authentint.infra.models.oauth import OAuthRefreshTokens
from authentint.keys import keystore
from authentint.oidc import refresh
from authentint.oidc.token import at_hash
from authentint.security.passwords import hash_token


def form(refresh_token: str, client_id: str = "wide-spa", **extra) -> dict:
    return {"grant_type": "refresh_token", "refresh_token": refresh_token, "client_id": client_id, **extra}


async def test_a_refresh_issues_new_tokens(client, s, offline_tokens, make_user, login_as):
    user = await make_user()
    sso = await login_as(user)
    first = await offline_tokens()

    r = await client.post("/token", data=form(first["refresh_token"]))

    assert r.status_code == 200
    assert r.headers["cache-control"] == "no-store"
    body = r.json()
    assert body["refresh_token"] != first["refresh_token"]
    assert body["scope"] == "offline_access openid svc:impots.read"

    keys = KeySet.import_key_set(await keystore.jwks(s))
    id_token = jwt.decode(body["id_token"], keys, algorithms=["RS256"]).claims
    assert id_token["sub"] == str(user.id) and id_token["sid"] == str(sso.id)
    assert "nonce" not in id_token  # OIDC Core §12.2
    assert id_token["at_hash"] == at_hash(body["access_token"])

    child = await s.scalar(select(OAuthRefreshTokens).where(OAuthRefreshTokens.token_hash == hash_token(body["refresh_token"])))
    parent = await s.get(OAuthRefreshTokens, hash_token(first["refresh_token"]))
    assert child.family_id == parent.family_id and child.parent_hash == parent.token_hash

async def test_a_reused_token_revokes_the_family_and_the_session(client, s, wide_spa, offline_tokens, make_user, login_as):
    sso = await login_as(await make_user())
    first = await offline_tokens()
    second = (await client.post("/token", data=form(first["refresh_token"]))).json()

    replay = await client.post("/token", data=form(first["refresh_token"]))
    assert replay.status_code == 400
    assert replay.json() == {"error": "invalid_grant"}

    # the legitimate child dies too: we can't tell which copy is the thief's
    after = await client.post("/token", data=form(second["refresh_token"]))
    assert after.json() == {"error": "invalid_grant"}

    family = (await s.scalars(select(OAuthRefreshTokens).where(OAuthRefreshTokens.session_id == sso.id)
                              .execution_options(populate_existing=True))).all()
    assert len(family) == 2 and all(t.revocation_reason == "refresh_reuse" for t in family)
    await s.refresh(sso)
    assert sso.revoked_at is not None and sso.revocation_reason == "refresh_reuse"

    event = await s.scalar(select(AuditEvents).where(AuditEvents.event_type == "token.refresh_reuse").order_by(AuditEvents.id.desc()))
    assert event.detail == {"severity": "high", "client_id": wide_spa.id}

async def test_another_clients_token_is_an_invalid_grant(client, s, offline_tokens, make_user, login_as):
    await login_as(await make_user())
    tokens = await offline_tokens()
    s.add(OAuthClients(id="other-spa", name="Other", type=ClientType.public, secret_hash=None, redirect_uris=[],
                       post_logout_redirect_uris=[], allowed_grants=["refresh_token"], allowed_scopes=[], require_consent=False))
    await s.flush()

    r = await client.post("/token", data=form(tokens["refresh_token"], client_id="other-spa"))
    assert r.json() == {"error": "invalid_grant"}

async def test_an_expired_token_is_an_invalid_grant(client, s, offline_tokens, make_user, login_as):
    await login_as(await make_user())
    tokens = await offline_tokens()
    await s.execute(update(OAuthRefreshTokens).values(expires_at=datetime(2000, 1, 1, tzinfo=UTC)))

    r = await client.post("/token", data=form(tokens["refresh_token"]))
    assert r.json() == {"error": "invalid_grant"}

async def test_a_refresh_may_narrow_the_scope_never_widen_it(client, offline_tokens, make_user, login_as):
    await login_as(await make_user())
    tokens = await offline_tokens()

    wider = await client.post("/token", data=form(tokens["refresh_token"], scope="openid svc:impots.write"))
    assert wider.json() == {"error": "invalid_scope"}

    narrower = await client.post("/token", data=form(tokens["refresh_token"], scope="openid"))
    assert narrower.status_code == 200
    assert narrower.json()["scope"] == "openid"

async def test_a_revoked_session_ends_its_refresh_tokens(client, s, offline_tokens, make_user, login_as):
    sso = await login_as(await make_user())
    tokens = await offline_tokens()
    # e.g. a password reset: it revokes the sessions, not the refresh tokens themselves
    await s.execute(update(Sessions).where(Sessions.id == sso.id).values(revoked_at=datetime.now(UTC)))

    r = await client.post("/token", data=form(tokens["refresh_token"]))
    assert r.json() == {"error": "invalid_grant"}

async def test_a_client_without_the_grant_is_unauthorized(client, spa):
    r = await client.post("/token", data=form("anything", client_id=spa.id))
    assert r.status_code == 400
    assert r.json() == {"error": "unauthorized_client"}

async def test_only_one_of_two_concurrent_rotations_wins(client, s, offline_tokens, make_user, login_as):
    await login_as(await make_user())
    tokens = await offline_tokens()
    row = await refresh.find(s, tokens["refresh_token"])

    # both requests passed the checks with the same row; the guarded UPDATE lets only the first through
    assert await refresh.rotate(s, row) is True
    assert await refresh.rotate(s, row) is False
