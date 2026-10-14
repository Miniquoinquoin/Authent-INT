"""
Account enumeration over HTTP (ADR §15: "réponses ET temps de réponse identiques pour un
utilisateur connu et inconnu"). test_login_constant_time.py proves the unknown path CALLS
Argon2; this proves it from the outside, the way an attacker measures it.

The activation and reset `request` endpoints have their identical-answer tests next to their
other invariants (test_activation_request.py, test_password_reset.py), not repeated here.

Every request comes from its own IP and targets its own account: the per-IP limit, the
per-account limit and the lockout would otherwise answer 429/423 and hide what is measured.
"""

import secrets
import statistics
import time

from authentint.security.passwords import hash_password


N = 15  # samples per side: the median ignores a few slow outliers (GC, a busy CI runner)


async def start(client, authorize_params) -> str:
    r = await client.get("/authorize", params=authorize_params())
    return r.headers["location"].split("uid=")[1]

async def login(make_client, authorize_params, ip: str, numero_fiscal: str):
    """One fresh browser: /authorize, then one login attempt. Returns (response, seconds spent on the login)."""

    async with make_client(ip) as browser:
        uid = await start(browser, authorize_params)
        t0 = time.perf_counter()
        r = await browser.post(f"/interaction/{uid}/login", json={"numero_fiscal": numero_fiscal, "password": "Wrong-password-1!"})
        return r, time.perf_counter() - t0

def unknown_numero() -> str:
    return "19" + "".join(secrets.choice("0123456789") for _ in range(11))  # random: hitting a real account is ~1 in 10^11


async def test_known_and_unknown_numero_fiscal_get_the_same_answer(make_client, authorize_params, alice, bob):
    wrong_password, _ = await login(make_client, authorize_params, "198.51.100.1", alice.numero_fiscal)
    not_activated, _ = await login(make_client, authorize_params, "198.51.100.2", bob.numero_fiscal)
    unknown, _ = await login(make_client, authorize_params, "198.51.100.3", unknown_numero())

    assert wrong_password.status_code == not_activated.status_code == unknown.status_code == 401
    assert wrong_password.json() == not_activated.json() == unknown.json()
    assert "set-cookie" not in wrong_password.headers and "set-cookie" not in unknown.headers

async def test_known_and_unknown_numero_fiscal_take_the_same_time(make_client, authorize_params, make_user):
    # Without DUMMY_HASH an unknown numero answers in a few ms and a wrong password after one Argon2
    # (tens of ms): a ratio of 10+. The 0.5-2 bound is loose on purpose (no flakes on a busy runner)
    # and still catches that. Checked by hand: skipping the dummy verification fails this test.
    password_hash = await hash_password("Correct-password-1!")  # one Argon2 hash shared by the N accounts
    known = []
    for _ in range(N):
        user = await make_user()
        user.password_hash = password_hash
        known.append(user.numero_fiscal)

    known_times, unknown_times = [], []
    for i in range(N):  # interleaved: a slowdown of the machine hits both sides alike
        r, t = await login(make_client, authorize_params, f"203.0.113.{i + 1}", known[i])
        assert r.status_code == 401
        known_times.append(t)
        r, t = await login(make_client, authorize_params, f"198.51.100.{i + 101}", unknown_numero())
        assert r.status_code == 401
        unknown_times.append(t)

    ratio = statistics.median(unknown_times) / statistics.median(known_times)
    assert 0.5 < ratio < 2.0, f"unknown/known median ratio {ratio:.2f}: response time reveals whether an account exists"
