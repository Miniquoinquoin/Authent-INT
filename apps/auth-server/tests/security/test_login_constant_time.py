"""
Credential check (flows/login.py). The last test is the security one: an unknown
numero fiscal must cost the same Argon2 verification as a wrong password, otherwise
response times reveal which numeros fiscaux have an account.
"""

from authentint.flows import login
from authentint.infra.models.identity import UserStatus


async def test_right_password_gives_the_user(s, alice, alice_password):
    assert await login.authenticate(s, "1801234567890", alice_password) == alice

async def test_wrong_password_gives_none(s, alice):
    assert await login.authenticate(s, "1801234567890", "wrong") is None

async def test_unknown_numero_fiscal_gives_none(s, alice, alice_password):
    assert await login.authenticate(s, "1809999999999", alice_password) is None

async def test_account_not_activated_yet_gives_none(s, alice, alice_password):
    # before activation there is no password at all: must not crash, must not log in
    alice.password_hash, alice.status = None, UserStatus.pending_activation
    assert await login.authenticate(s, "1801234567890", alice_password) is None

async def test_an_unknown_numero_fiscal_still_pays_one_argon2_verification(s, alice, monkeypatch):
    calls = []

    async def counting_verify(hash, pwd):
        calls.append(hash)
        return False

    monkeypatch.setattr(login, "verify_password", counting_verify)
    await login.authenticate(s, "1809999999999", "whatever")
    assert calls == [login.DUMMY_HASH]
