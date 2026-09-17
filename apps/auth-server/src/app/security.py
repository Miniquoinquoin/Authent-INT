"""Hashing, token and OTP generation, constant-time comparison.

The **only** module in the codebase that imports `argon2`, `hashlib`, `secrets`
or `hmac`. "Is every token stored hashed?" (§15) is then one file to read
instead of a grep with a false-negative rate (§10, boundary 2).

Two hash families, and the split is deliberate:

* **Argon2id** for anything a human chose or could guess — passwords, and the
  six-digit OTP. A 6-digit code has 20 bits of entropy; a plain digest of one is
  brute-forced from a cache dump in a second, and Argon2 is what makes that dump
  worthless. It needs no shared secret, so it survives `--scale 3` where a
  per-worker HMAC key would not (§14).
* **SHA-256** for the high-entropy handles we generate — activation tokens and
  session cookies. The entropy is in the 256-bit token, not in the KDF, and the
  lookup has to be deterministic: you cannot `SELECT ... WHERE token_hash = ?`
  against a salted hash.
"""

import asyncio
import hashlib
import hmac
import secrets

from argon2 import PasswordHasher
from argon2.exceptions import VerificationError, VerifyMismatchError

_hasher = PasswordHasher()

#: Verified against when the user does not exist, so an unknown numéro fiscal
#: costs exactly what a known one costs. Timing must not become the oracle the
#: response body is not (P§7 step 4).
DUMMY_HASH = _hasher.hash("a password no account has")


async def hash_password(password: str) -> str:
    """Argon2id, off the event loop.

    §3 flags this as a day-one decision, not a post-k6 fix: hashing on the event
    loop stalls every concurrent request, not just the login being hashed.
    """
    return await asyncio.to_thread(_hasher.hash, password)


async def verify_password(password_hash: str, password: str) -> bool:
    def _verify() -> bool:
        try:
            return _hasher.verify(password_hash, password)
        except (VerifyMismatchError, VerificationError):
            return False

    return await asyncio.to_thread(_verify)


def digest(value: str) -> str:
    """SHA-256 hex of a high-entropy handle. Deterministic, so it can be looked up."""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def new_token() -> tuple[str, str]:
    """A URL-safe activation token. Returns `(plaintext, digest)`.

    The plaintext goes in the mail and is never stored (§6).
    """
    token = secrets.token_urlsafe(32)
    return token, digest(token)


def new_session_token() -> tuple[str, str]:
    """The opaque session cookie value. Returns `(plaintext, digest)`."""
    token = secrets.token_urlsafe(32)
    return token, digest(token)


async def new_otp() -> tuple[str, str]:
    """Six digits from a CSPRNG. Returns `(code, argon2_hash)`.

    `randbelow` rather than digits drawn in a loop: one uniform draw, no bias.
    """
    code = f"{secrets.randbelow(1_000_000):06d}"
    return code, await asyncio.to_thread(_hasher.hash, code)


async def verify_otp(code_hash: str, code: str) -> bool:
    return await verify_password(code_hash, code)


def same(a: str, b: str) -> bool:
    """Constant-time comparison. For digests, where both sides are ours."""
    return hmac.compare_digest(a, b)


def pseudonym(value: str) -> str:
    """A stable, non-reversible key for a rate-limit counter.

    §5 keeps the numéro fiscal out of anything that is not the identity
    database — including Valkey key names, which are readable by anyone holding
    a `MONITOR` connection.
    """
    return digest(value)[:32]
