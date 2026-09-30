"""sessions/queries.py — B1."""

from datetime import UTC
from datetime import datetime

from starlette.requests import Request

from authentint.infra.models.audit import Sessions
from authentint.sessions import queries as sessions


def browser(ip: str = "203.0.113.7", user_agent: str = "Firefox on Linux") -> Request:
    """A minimal HTTP request, as FastAPI would hand it to a route."""

    return Request({"type": "http", "headers": [(b"user-agent", user_agent.encode())], "client": (ip, 51000)})


async def test_create_stores_the_session_in_the_database(s, alice):
    created = await sessions.create(s, alice, browser())
    assert created.id is not None  # the database gave it an id
    stored = await s.get(Sessions, created.id)
    assert stored is not None
    assert stored.user_id == alice.id

async def test_the_session_remembers_the_device(s, alice):
    created = await sessions.create(s, alice, browser(ip="198.51.100.4", user_agent="Chrome on Android"))
    assert str(created.ip_address) == "198.51.100.4"
    assert created.device_label == "Chrome on Android"

async def test_a_new_session_is_alive(s, alice):
    created = await sessions.create(s, alice, browser())
    assert created.revoked_at is None
    assert created.expires_at > datetime.now(UTC)
