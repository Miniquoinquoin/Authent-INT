"""
Rate limit on POST /interaction/{uid}/login, per IP. The lockout protects ONE account
against many guesses; this protects ALL accounts against one source (and stops it
from locking thousands of accounts on purpose).
"""

from datetime import timedelta

from authentint.flows.interaction import LOGIN_LIMIT
from authentint.security import ratelimit


async def start(client, authorize_params) -> str:
    r = await client.get("/authorize", params=authorize_params())
    return r.headers["location"].split("uid=")[1]

async def attempt(client, uid, alice, password):
    return await client.post(f"/interaction/{uid}/login", json={"numero_fiscal": alice.numero_fiscal, "password": password})


async def test_over_the_limit_even_the_right_password_is_refused(make_client, authorize_params, alice, alice_password):
    async with make_client("203.0.113.66") as attacker:
        uid = await start(attacker, authorize_params)
        for _ in range(LOGIN_LIMIT):
            # wrong numeros fiscaux: spread over many accounts, so the per-account lockout never triggers
            r = await attacker.post(f"/interaction/{uid}/login", json={"numero_fiscal": "1809999999999", "password": "x"})
            assert r.status_code == 401
        r = await attempt(attacker, uid, alice, alice_password)
        assert r.status_code == 429

async def test_one_ip_over_the_limit_does_not_block_another(make_client, authorize_params, alice, alice_password):
    async with make_client("203.0.113.66") as attacker, make_client("198.51.100.20") as alice_browser:
        uid = await start(attacker, authorize_params)
        for _ in range(LOGIN_LIMIT + 1):
            await attacker.post(f"/interaction/{uid}/login", json={"numero_fiscal": "1809999999999", "password": "x"})
        r = await attempt(alice_browser, await start(alice_browser, authorize_params), alice, alice_password)
        assert r.status_code == 200

async def test_the_limiter_fails_closed():
    # invariant 9: if the counter can't be read, refuse rather than let everything through
    class BrokenDatabase:
        async def scalar(self, *args, **kwargs):
            raise ConnectionError("postgres is down")

    assert await ratelimit.hit(BrokenDatabase(), "login:ip:1.2.3.4", 10, timedelta(minutes=1)) is False
