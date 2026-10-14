"""
Credential check for POST /interaction/{uid}/login (B1).

Constant time: Argon2 takes ~100 ms on purpose. If an unknown numero fiscal were
answered without hashing, it would come back ~100 ms faster than a wrong password,
and an attacker timing the answers could list which numeros fiscaux have an account.
So a password is ALWAYS verified: against the user's hash, or against DUMMY_HASH.
"""

import secrets

from datetime import UTC
from datetime import datetime
from datetime import timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from authentint.audit import audit
from authentint.infra.models.identity import User
from authentint.infra.models.identity import UserStatus
from authentint.security.passwords import pwd_hasher
from authentint.security.passwords import verify_password
from authentint.users import queries as users


# The hash of a random secret nobody knows: same Argon2 cost as a real hash, can never match
DUMMY_HASH = pwd_hasher.hash(secrets.token_urlsafe(32))

MAX_FAILURES = 5                  # wrong passwords in a row before the account locks (architecture.md §4)
LOCKOUT = timedelta(minutes=15)   # how long it stays locked

# ADR §16 "par IP et par compte": attempts per account, from any IP. Above MAX_FAILURES so the lockout
# (and its 423) still comes first; this caps what a botnet spends hammering a locked account.
ACCOUNT_LIMIT = 10
ACCOUNT_WINDOW = timedelta(minutes=1)


def account_bucket(numero_fiscal_hmac: str) -> str:
    """The per-account bucket: keyed by the HMAC, the numero fiscal itself is never stored (ADR §8)."""

    return f"login:account:{numero_fiscal_hmac}"


class AccountLocked(Exception):
    """Too many failures, or locked by an admin: answered 423 whatever the password."""


def is_locked(user: User, now: datetime) -> bool:
    if user.status in (UserStatus.locked, UserStatus.disabled):
        return True  # by an admin: until an admin unlocks it
    return user.locked_until is not None and user.locked_until > now  # temporary, after MAX_FAILURES

def record_failure(user: User, now: datetime) -> None:
    """One more wrong password. The MAX_FAILURES-th locks the account for LOCKOUT and restarts the count."""

    user.failed_login_count += 1
    if user.failed_login_count >= MAX_FAILURES:
        user.locked_until = now + LOCKOUT
        user.failed_login_count = 0


async def authenticate(session: AsyncSession, numero_fiscal: str, password: str) -> User | None:
    """The user when numero fiscal AND password match, else None. Same cost in every case."""

    user = await users.by_numero_fiscal(session, numero_fiscal)

    use_hash = user.password_hash if user is not None and user.password_hash is not None else DUMMY_HASH
    ok = await verify_password(use_hash, password)

    now = datetime.now(UTC)
    if user is not None and is_locked(user, now):
        # after Argon2 (same time as always), before looking at `ok`: while locked,
        # the answer never tells whether the password was right
        await audit.emit(session, "login.locked", actor=user.id, outcome="failure", detail={})
        raise AccountLocked()

    if not ok:
        if user is not None:
            record_failure(user, now)  # the route commits it, so the count survives the 401

        await audit.emit(session, "login.failure", actor=user.id if user is not None else None, outcome="failure", detail={"reason": "bad_credentials"})
        return None

    user.failed_login_count = 0  # a success forgives the previous failures
    return user
