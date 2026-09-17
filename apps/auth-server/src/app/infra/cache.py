"""Valkey: interaction state, OTP challenges, rate limit counters.

This module owns **every key name**. A caller passes an identifier; it never
passes, sees or builds a key. Key-format drift is how an `rl:` counter quietly
stops matching the key that increments it, and a rate limiter that has silently
stopped counting is the failure you find during the incident (§10).

Everything here fails **closed**: if Valkey is unreachable the caller gets
`CacheUnavailable` and rejects the request. Failing open would remove
brute-force protection at precisely the moment something is going wrong
(§11b rule 3). This is the one place degradation is deliberately ungraceful.
"""

import json
import uuid
from typing import Any

import redis.asyncio as redis
from redis.exceptions import RedisError

from app.config import settings

_client = redis.from_url(settings().valkey_url, decode_responses=True)


class CacheUnavailable(RuntimeError):
    """Valkey is unreachable. Callers reject; they never continue."""


# ------------------------------------------------------------------ key names
# The only place in the codebase where these strings exist.
def _interaction(uid: str) -> str:
    return f"int:{uid}"


def _otp(uid: str) -> str:
    return f"otp:{uid}"


def _rate(scope: str, key: str) -> str:
    return f"rl:{scope}:{key}"


# ---------------------------------------------------------------- interaction
async def interaction_create(state: dict[str, Any]) -> str:
    """Mint a `uid` and store the opaque server-side state behind it."""
    uid = uuid.uuid4().hex
    try:
        await _client.set(_interaction(uid), json.dumps(state), ex=settings().interaction_ttl_s)
    except RedisError as exc:  # pragma: no cover - exercised by the Valkey-down test
        raise CacheUnavailable from exc
    return uid


async def interaction_get(uid: str) -> dict[str, Any] | None:
    try:
        raw = await _client.get(_interaction(uid))
    except RedisError as exc:
        raise CacheUnavailable from exc
    return json.loads(raw) if raw else None


async def interaction_set(uid: str, state: dict[str, Any]) -> None:
    """Overwrite the state, keeping the original expiry — the 10 minutes are on
    the whole authentication, not on its slowest step."""
    try:
        await _client.set(_interaction(uid), json.dumps(state), keepttl=True)
    except RedisError as exc:
        raise CacheUnavailable from exc


async def interaction_drop(uid: str) -> None:
    try:
        await _client.delete(_interaction(uid))
    except RedisError as exc:
        raise CacheUnavailable from exc


# ------------------------------------------------------------------------ OTP
async def otp_put(uid: str, code_hash: str, purpose: str) -> None:
    """Store the **hash** of the challenge. Never the plaintext code (§6)."""
    key = _otp(uid)
    try:
        async with _client.pipeline(transaction=True) as pipe:
            pipe.delete(key)
            pipe.hset(key, mapping={"code_hash": code_hash, "purpose": purpose, "attempts": 0})
            pipe.expire(key, settings().otp_ttl_s)
            await pipe.execute()
    except RedisError as exc:
        raise CacheUnavailable from exc


async def otp_get(uid: str) -> dict[str, str] | None:
    try:
        data = await _client.hgetall(_otp(uid))
    except RedisError as exc:
        raise CacheUnavailable from exc
    return data or None


async def otp_attempt(uid: str) -> int:
    """Atomically count one attempt and return the new total."""
    try:
        return int(await _client.hincrby(_otp(uid), "attempts", 1))
    except RedisError as exc:
        raise CacheUnavailable from exc


async def otp_consume(uid: str) -> None:
    """Consume the challenge — on success *and* on attempt exhaustion (§9)."""
    try:
        await _client.delete(_otp(uid))
    except RedisError as exc:
        raise CacheUnavailable from exc


# ---------------------------------------------------------------- rate limits
async def rate_limit_hit(scope: str, key: str, limit: int, window_s: int) -> bool:
    """Count one request. Returns False when the caller is over the limit.

    `key` is an opaque identifier chosen by the caller — an IP, or a pseudonym
    of the numéro fiscal. Never the numéro fiscal itself: §5 keeps it out of
    anything that is not the identity database.
    """
    name = _rate(scope, key)
    try:
        # One round trip, and EXPIRE NX only stamps a TTL the key does not have
        # yet. Two calls with an `if count == 1` between them left a key with
        # no TTL whenever the second call failed — a counter that never
        # resets is a permanent lockout for that IP or account.
        async with _client.pipeline(transaction=True) as pipe:
            pipe.incr(name)
            pipe.expire(name, window_s, nx=True)
            count, _ = await pipe.execute()
    except RedisError as exc:
        raise CacheUnavailable from exc
    return int(count) <= limit


async def ping() -> None:
    """Raise if Valkey is unreachable. Used by /health/ready."""
    try:
        await _client.ping()
    except RedisError as exc:
        raise CacheUnavailable from exc
