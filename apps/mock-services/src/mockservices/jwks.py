"""
The issuer's public keys, downloaded once and kept in memory (ADR §11, docs/architecture.md §3).

A request never calls the auth-server, except when its token names a kid we don't hold:
that usually means a rotation since our last download, so we refresh, at most once per cooldown.
"""

import asyncio
import logging
import time
from collections.abc import Callable

import httpx
from joserfc.errors import JoseError
from joserfc.jwk import RSAKey


log = logging.getLogger(__name__)


class JwksUnavailable(Exception):
    """No key set has ever been loaded: we can't tell a valid token from a forged one."""


class JwksClient:
    def __init__(
        self,
        issuer: str,
        ca_bundle: str | None = None,
        cooldown: float = 30.0,
        retry_delay: float = 2.0,
        transport: httpx.AsyncBaseTransport | None = None,  # tests plug an httpx.MockTransport here
        clock: Callable[[], float] = time.monotonic,
    ):
        self.issuer = issuer
        self.cooldown = cooldown
        self.retry_delay = retry_delay
        self.clock = clock
        self._keys: dict[str, RSAKey] | None = None
        self._next_fetch_at = 0.0  # no download before this instant, success or failure
        self._lock = asyncio.Lock()
        # verify=True (system store) when no bundle is given; never verify=False
        self._http = httpx.AsyncClient(verify=ca_bundle or True, transport=transport, timeout=5.0)

    @property
    def loaded(self) -> bool:
        return self._keys is not None

    async def key(self, kid: str) -> RSAKey | None:
        """The key for this kid, or None. Refreshes at most once per cooldown, whoever asks."""

        if self._keys is not None and kid in self._keys:
            return self._keys[kid]

        async with self._lock:
            # Another request may have refreshed while we waited for the lock
            if self._keys is not None and kid in self._keys:
                return self._keys[kid]
            # Debounce: without it, tokens with random kids turn every request into a call
            # to the auth-server, the very denial of service JWKS is meant to avoid
            if self.clock() >= self._next_fetch_at:
                await self._fetch()

        if self._keys is None:
            raise JwksUnavailable()
        return self._keys.get(kid)

    async def ensure_loaded(self) -> bool:
        """For startup and /health/ready: loads the key set if we have none (same rate limit)."""

        if self._keys is None:
            async with self._lock:
                if self._keys is None and self.clock() >= self._next_fetch_at:
                    await self._fetch()
        return self._keys is not None

    async def _fetch(self) -> None:
        try:
            self._keys = await self._download()
            self._next_fetch_at = self.clock() + self.cooldown
            log.info("JWKS loaded from %s: kids %s", self.issuer, sorted(self._keys))
        except (httpx.HTTPError, ValueError, KeyError, TypeError, JoseError) as exc:
            # Keep the keys we had: an issuer outage must not invalidate tokens we can still verify.
            # Cold start (auth-server not up yet): retry soon. Otherwise the cooldown still holds.
            self._next_fetch_at = self.clock() + (self.retry_delay if self._keys is None else self.cooldown)
            log.warning("JWKS refresh from %s failed: %r", self.issuer, exc)

    async def _download(self) -> dict[str, RSAKey]:
        conf = await self._get(f"{self.issuer}/.well-known/openid-configuration")
        # The discovery document must speak for the issuer we trust, character for character
        # (docs/architecture.md §1.1): otherwise jwks_uri could point at someone else's keys
        if conf.get("issuer") != self.issuer:
            raise ValueError(f"discovery issuer {conf.get('issuer')!r} != {self.issuer!r}")
        jwks = await self._get(conf["jwks_uri"])

        keys: dict[str, RSAKey] = {}
        for data in jwks["keys"]:
            # Only RSA signing keys meant for RS256; anything else in the set is ignored
            if data.get("kty") != "RSA" or data.get("use", "sig") != "sig" or data.get("alg", "RS256") != "RS256":
                continue
            if not isinstance(data.get("kid"), str):
                continue
            keys[data["kid"]] = RSAKey.import_key(data)
        if not keys:
            raise ValueError("no RS256 key in the JWKS")
        return keys

    async def _get(self, url: str) -> dict:
        response = await self._http.get(url)
        response.raise_for_status()
        body = response.json()
        if not isinstance(body, dict):
            raise ValueError(f"{url} did not return a JSON object")
        return body

    async def aclose(self) -> None:
        await self._http.aclose()
