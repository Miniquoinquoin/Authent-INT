"""App, database, Valkey and Mailpit fixtures. Truncate between tests.

Against **the compose Postgres and Valkey** — no testcontainers. The stack is
already up (§14); a second mechanism for getting a database earns nothing.
"""

import logging.config
from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.infra import cache
from app.infra.db import SessionLocal
from app.main import LOGGING, app

logging.config.dictConfig(LOGGING)

TABLES = ("sessions", "activation_tokens", "users")
MAILPIT = "http://localhost:8025/api/v1"


@pytest.fixture(autouse=True)
async def clean() -> AsyncIterator[None]:
    """Every test starts from an empty database, an empty Valkey and an empty
    inbox. Shared state between tests is how a suite starts lying."""
    async with SessionLocal() as db:
        await db.execute(text(f"TRUNCATE {', '.join(TABLES)} CASCADE"))
        await db.commit()
    await cache._client.flushdb()
    try:
        httpx.delete(f"{MAILPIT}/messages", timeout=2)
    except httpx.HTTPError:  # pragma: no cover - mailpit is optional for unit tests
        pass
    yield


@pytest.fixture
async def db() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        yield session


@pytest.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app)
    # **http**, because that is what the dev stack serves and what a browser
    # therefore sees. An earlier version of this fixture used https, which made
    # a `Secure` cookie look fine here while Safari silently refused to send it
    # back over http and every login dead-ended at the dashboard. A test client
    # on a scheme the product does not use tests a product we do not ship.
    async with httpx.AsyncClient(transport=transport, base_url="http://auth.test") as c:
        yield c


class Inbox:
    """The Mailpit inbox, as the tests need to see it."""

    def messages(self) -> list[dict]:
        return httpx.get(f"{MAILPIT}/messages", timeout=5).json()["messages"]

    def count(self) -> int:
        return len(self.messages())

    def latest_body(self) -> str:
        msg = self.messages()[0]
        return httpx.get(f"{MAILPIT}/message/{msg["ID"]}", timeout=5).json()["HTML"]


@pytest.fixture
def inbox() -> Inbox:
    return Inbox()


@pytest.fixture
def fixture_file(tmp_path: Path) -> Path:
    """A writable copy of the directory fixture, so a test can make an entry
    disappear without editing the repository."""
    target = tmp_path / "users.json"
    target.write_text(settings().fixture_file.read_text(encoding="utf-8"), encoding="utf-8")
    return target


@pytest.fixture
def caplog_json(caplog: pytest.LogCaptureFixture) -> pytest.LogCaptureFixture:
    caplog.set_level(logging.INFO)
    return caplog
