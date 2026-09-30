"""users/queries.py — B1."""

from authentint.users import queries as users


async def test_finds_a_user_by_numero_fiscal(s, alice):
    found = await users.by_numero_fiscal(s, "1801234567890")
    assert found is not None
    assert found.id == alice.id

async def test_unknown_numero_fiscal_gives_none(s, alice):
    assert await users.by_numero_fiscal(s, "1809999999999") is None
