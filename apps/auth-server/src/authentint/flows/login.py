"""
Credential check for POST /interaction/{uid}/login (B1).

Constant time: Argon2 takes ~100 ms on purpose. If an unknown numero fiscal were
answered without hashing, it would come back ~100 ms faster than a wrong password,
and an attacker timing the answers could list which numeros fiscaux have an account.
So a password is ALWAYS verified: against the user's hash, or against DUMMY_HASH.
"""

import secrets

from sqlalchemy.ext.asyncio import AsyncSession

from authentint.infra.models.identity import User
from authentint.security.passwords import pwd_hasher
from authentint.security.passwords import verify_password
from authentint.users import queries as users


# The hash of a random secret nobody knows: same Argon2 cost as a real hash, can never match
DUMMY_HASH = pwd_hasher.hash(secrets.token_urlsafe(32))


async def authenticate(session: AsyncSession, numero_fiscal: str, password: str) -> User | None:
    """The user when numero fiscal AND password match, else None. Same cost in every case."""

    user = await users.by_numero_fiscal(session, numero_fiscal)

    use_hash = user.password_hash if user is not None and user.password_hash is not None else DUMMY_HASH
    ok = await verify_password(use_hash, password) 
    
    return user if ok else None
