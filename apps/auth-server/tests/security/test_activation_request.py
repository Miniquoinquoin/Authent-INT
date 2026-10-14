"""
POST /account/activation/request (flows/activation.py) — B1.
Invariant 8: the answer never tells whether the account exists.
The link's token is random, and only its hash is stored.
"""

import re

from sqlalchemy import select

from authentint.infra.models.identity import ActivationTokens
from authentint.security.passwords import hash_token


async def ask(client, numero_fiscal: str):
    return await client.post("/account/activation/request", json={"numero_fiscal": numero_fiscal})

def token_in(mail: dict) -> str:
    return re.search(r"token=([\w-]+)", mail["body"]).group(1)


async def test_a_pending_account_receives_a_link(client, mailbox, bob):
    r = await ask(client, bob.numero_fiscal)
    assert r.status_code == 202
    [mail] = mailbox.sent
    assert mail["to"] == bob.email
    assert "/activate?token=" in mail["body"]

async def test_the_database_stores_the_hash_never_the_token(client, s, mailbox, bob):
    await ask(client, bob.numero_fiscal)
    token = token_in(mailbox.sent[0])
    [row] = await s.scalars(select(ActivationTokens).where(ActivationTokens.user_id == bob.id))
    assert row.token_hash != token              # a database dump gives no usable link...
    assert row.token_hash == hash_token(token)  # ...but the server can still recognise it

async def test_every_link_is_different_and_unguessable(client, mailbox, bob):
    await ask(client, bob.numero_fiscal)
    await ask(client, bob.numero_fiscal)
    first, second = (token_in(m) for m in mailbox.sent)
    assert first != second
    assert len(first) >= 40  # 32 random bytes in base64: ~2^256 possibilities

async def test_the_answer_never_tells_whether_the_account_exists(client, mailbox, alice, bob):
    pending = await ask(client, bob.numero_fiscal)      # exists, not active yet: gets a mail
    active = await ask(client, alice.numero_fiscal)     # exists, already active: no mail
    unknown = await ask(client, "1800000000000")        # doesn't exist: no mail
    assert pending.status_code == active.status_code == unknown.status_code == 202
    assert pending.json() == active.json() == unknown.json()
    assert len(mailbox.sent) == 1
