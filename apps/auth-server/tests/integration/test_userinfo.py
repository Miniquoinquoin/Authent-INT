"""/userinfo (OIDC Core §5.3): the user behind an IdP-audience token, never the numero fiscal, RFC 6750 errors."""

from authentint.infra.models.identity import UserStatus


async def test_userinfo_describes_the_user(client, make_user, access_token):
    user = await make_user()
    token = await access_token(user, "openid svc:impots.read")

    for method in (client.get, client.post):
        r = await method("/userinfo", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200
        assert r.json() == {"sub": str(user.id), "name": "User Test", "given_name": "User", "family_name": "Test",
                            "role": "contribuable"}
        assert user.numero_fiscal not in r.text

async def test_the_email_needs_the_email_scope(client, make_user, access_token):
    user = await make_user()
    token = await access_token(user, "openid email")

    r = await client.get("/userinfo", headers={"Authorization": f"Bearer {token}"})
    assert r.json()["email"] == user.email

async def test_a_service_only_token_is_refused(client, make_user, access_token):
    token = await access_token(await make_user(), "svc:impots.read")  # aud svc-impots alone

    r = await client.get("/userinfo", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 401
    assert r.headers["www-authenticate"] == 'Bearer error="invalid_token"'

async def test_a_garbage_token_is_refused(client):
    r = await client.get("/userinfo", headers={"Authorization": "Bearer not-a-jwt"})
    assert r.status_code == 401
    assert r.headers["www-authenticate"] == 'Bearer error="invalid_token"'

async def test_no_token_gets_the_bare_challenge(client):
    r = await client.get("/userinfo")
    assert r.status_code == 401
    assert r.headers["www-authenticate"] == "Bearer"

async def test_a_disabled_user_is_refused(client, s, make_user, access_token):
    user = await make_user()
    token = await access_token(user, "openid")
    user.status = UserStatus.disabled
    await s.flush()

    r = await client.get("/userinfo", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 401
