"""
The fake issuer of seam S2 (ADR §17): a throwaway RSA key pair generated for this test run only,
and an httpx.MockTransport that serves its discovery document and JWKS. No network, no auth-server.

TEST-ONLY: the private keys below live in memory for one pytest run and are never written to disk.
When B2's real tokens arrive, nothing here changes: the service reads the real issuer's JWKS.
"""

import time
import uuid

import httpx
import pytest
from joserfc import jwt
from joserfc.jwk import RSAKey

from mockservices.jwks import JwksClient


ISSUER = "https://auth.authentint.localhost"
JWKS_URI = f"{ISSUER}/.well-known/jwks.json"


class FakeIssuer:
    """Plays the auth-server's /.well-known endpoints and signs tokens like B2 does."""

    def __init__(self, pool: dict[str, RSAKey]):
        self.pool = pool  # keys generated for the run; only those in self.keys are published
        self.keys: list[RSAKey] = [pool["kid-1"]]
        self.jwks_calls = 0
        self.discovery_issuer = ISSUER
        self.down = False

    @property
    def active(self) -> RSAKey:
        return self.keys[-1]

    def rotate(self, kid: str) -> RSAKey:
        """Publishes a new key and signs with it from now on, as keys/keystore.rotate() does."""
        self.keys.append(self.pool[kid])
        return self.active

    def handler(self, request: httpx.Request) -> httpx.Response:
        if self.down:
            raise httpx.ConnectError("auth-server not up yet", request=request)
        if request.url == f"{ISSUER}/.well-known/openid-configuration":
            return httpx.Response(200, json={"issuer": self.discovery_issuer, "jwks_uri": JWKS_URI})
        if request.url == JWKS_URI:
            self.jwks_calls += 1
            return httpx.Response(200, json={"keys": [k.as_dict(private=False) for k in self.keys]})
        return httpx.Response(404)

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handler)

    def token(self, key: RSAKey | None = None, header: dict | None = None, **overrides) -> str:
        """An access token shaped like domain/claims.py AccessToken, signed RS256 with typ at+jwt."""

        key = key or self.active
        now = int(time.time())
        claims = {
            "iss": ISSUER,
            "sub": str(uuid.UUID(int=42)),
            "aud": ["svc-impots"],
            "client_id": "portail-web",
            "scope": "openid svc:impots.read",
            "exp": now + 600,
            "iat": now,
            "jti": uuid.uuid4().hex,
            "sid": str(uuid.UUID(int=7)),
            "acr": "pwd",
        }
        claims.update(overrides)
        claims = {k: v for k, v in claims.items() if v is not None}  # override=None drops a claim
        return jwt.encode({"alg": "RS256", "typ": "at+jwt", "kid": key.kid, **(header or {})}, claims, key)


def new_key(kid: str) -> RSAKey:
    return RSAKey.generate_key(2048, parameters={"kid": kid, "use": "sig", "alg": "RS256"})


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture(scope="session")
def key_pool() -> dict[str, RSAKey]:
    # RSA generation is slow: one pool per run, shared by every FakeIssuer
    return {kid: new_key(kid) for kid in ("kid-1", "kid-2", "attacker")}


@pytest.fixture
def issuer(key_pool) -> FakeIssuer:
    return FakeIssuer(key_pool)


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def jwks(issuer, clock) -> JwksClient:
    return JwksClient(ISSUER, cooldown=30.0, retry_delay=2.0, transport=issuer.transport(), clock=clock)
