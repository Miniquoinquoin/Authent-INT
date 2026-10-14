"""JWKS cache rules (ADR §11): cache, refresh once on an unknown kid, rate-limit that refresh."""

import asyncio

import httpx
import pytest

from mockservices.jwks import JwksClient, JwksUnavailable

from conftest import ISSUER


async def test_the_key_set_is_downloaded_once_then_served_from_memory(jwks, issuer):
    for _ in range(5):
        assert await jwks.key("kid-1") is not None

    assert issuer.jwks_calls == 1


async def test_an_unknown_kid_triggers_exactly_one_refresh(jwks, issuer, clock):
    await jwks.key("kid-1")
    clock.now += 31  # past the cooldown

    assert await jwks.key("bogus") is None
    assert issuer.jwks_calls == 2


async def test_a_second_unknown_kid_inside_the_debounce_window_triggers_none(jwks, issuer, clock):
    await jwks.key("kid-1")
    clock.now += 31
    await jwks.key("bogus-1")
    calls = issuer.jwks_calls

    clock.now += 10  # still inside the 30 s window
    for i in range(100):
        assert await jwks.key(f"bogus-{i}") is None

    assert issuer.jwks_calls == calls


async def test_a_rotated_key_is_picked_up_by_the_refresh(jwks, issuer, clock):
    await jwks.key("kid-1")
    issuer.rotate("kid-2")
    clock.now += 31

    assert await jwks.key("kid-2") is not None
    assert await jwks.key("kid-1") is not None  # the retired key stays usable while published


async def test_the_discovery_issuer_must_match_exactly(jwks, issuer):
    issuer.discovery_issuer = ISSUER + "/"

    with pytest.raises(JwksUnavailable):
        await jwks.key("kid-1")


async def test_the_service_starts_without_the_issuer_and_loads_keys_once_it_is_up(jwks, issuer, clock):
    issuer.down = True
    assert await jwks.ensure_loaded() is False

    issuer.down = False
    assert await jwks.ensure_loaded() is False  # retry delay not elapsed: no hammering
    clock.now += 2
    assert await jwks.ensure_loaded() is True


async def test_an_issuer_outage_keeps_the_keys_already_loaded(jwks, issuer, clock):
    await jwks.key("kid-1")
    issuer.down = True
    clock.now += 31

    assert await jwks.key("bogus") is None  # refresh failed
    assert await jwks.key("kid-1") is not None


async def test_keys_that_are_not_rs256_signing_keys_are_ignored(issuer, clock):
    rsa = issuer.active.as_dict(private=False)
    weird = [
        {**rsa, "kid": "enc", "use": "enc"},
        {**rsa, "kid": "ps256", "alg": "PS256"},
        {"kty": "oct", "kid": "hmac", "k": "c2VjcmV0"},
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("jwks.json"):
            return httpx.Response(200, json={"keys": [rsa, *weird]})
        return issuer.handler(request)

    client = JwksClient(ISSUER, transport=httpx.MockTransport(handler), clock=clock)

    assert await client.key("kid-1") is not None
    for kid in ("enc", "ps256", "hmac"):
        assert await client.key(kid) is None


async def test_a_burst_of_concurrent_unknown_kids_costs_one_download(jwks, issuer, clock):
    await jwks.key("kid-1")
    clock.now += 31

    await asyncio.gather(*(jwks.key(f"bogus-{i}") for i in range(50)))

    assert issuer.jwks_calls == 2
