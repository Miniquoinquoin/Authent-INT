"""
The numero fiscal is never stored (lesson 11, decision C: HMAC only). A stolen copy
of the users table must not give back a single numero fiscal.
"""

import hashlib
import hmac

from sqlalchemy import text

from authentint.config import settings
from authentint.security.identifiers import numero_fiscal_digest


async def test_the_users_table_holds_no_numero_fiscal(s, alice, bob):
    # read the rows as raw text, like someone with a dump of the database would
    rows = (await s.execute(text("SELECT * FROM users"))).all()
    dump = " ".join(str(value) for row in rows for value in row)
    assert alice.numero_fiscal not in dump
    assert bob.numero_fiscal not in dump

async def test_a_plain_sha256_would_not_be_enough():
    # SHA-256 without a key: anyone can recompute it for all 10^13 numeros. The stored value must differ.
    assert numero_fiscal_digest("1801234567890") != hashlib.sha256(b"1801234567890").hexdigest()

async def test_it_is_the_hmac_sha256_with_the_secret_key():
    # pins the formula: the migration that converted the existing rows uses exactly this one
    expected = hmac.new(settings.numero_fiscal_key.encode(), b"1801234567890", hashlib.sha256).hexdigest()
    assert numero_fiscal_digest("1801234567890") == expected

async def test_same_numero_same_digest_so_login_can_find_it():
    assert numero_fiscal_digest("1801234567890") == numero_fiscal_digest("1801234567890")
    assert numero_fiscal_digest("1801234567890") != numero_fiscal_digest("1801234567891")
