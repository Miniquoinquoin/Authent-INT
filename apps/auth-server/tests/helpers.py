"""Helpers the tests call directly.

Deliberately not in `conftest.py`: pytest imports that file itself, and a test
module that *also* imports it by name gets a second copy under a second module
name — with every fixture registered twice. Fixtures live in conftest, plain
functions live here.
"""

from pathlib import Path

from app.infra import cache

#: Long enough for the ANSSI-style length rule, and not a composition puzzle.
PASSWORD = "correct cheval pile agrafe 42"

ADMIN_NF = "1801234567891"
AGENT_NF = "1802234567892"
TRANSIENT_NF = "1806234567896"


async def seed(db, path) -> None:
    """Run the real provisioning feed, so tests start from real rows."""
    from app.directory import FixtureDirectory
    from app.sync import run

    await run(FixtureDirectory(path), db)


async def activate_directly(db, numero_fiscal: str, password: str = PASSWORD):
    """Give an account a password without walking the mail flow.

    Setup, not a path under test: the activation flow has its own tests, and
    every other test would otherwise pay for an SMTP round trip.
    """
    from datetime import UTC, datetime

    from sqlalchemy import select

    from app import security
    from app.models import Status, User

    user = await db.scalar(select(User).where(User.numero_fiscal == numero_fiscal))
    user.password_hash = await security.hash_password(password)
    user.status = Status.ACTIVE
    user.password_changed_at = datetime.now(UTC)
    await db.commit()
    return user


async def start_interaction(client) -> str:
    response = await client.post("/interaction")
    assert response.status_code == 201
    return response.json()["uid"]


async def login(client, numero_fiscal: str, password: str = PASSWORD, uid: str | None = None):
    uid = uid or await start_interaction(client)
    return await client.post(
        f"/interaction/{uid}/login", json={"numero_fiscal": numero_fiscal, "password": password}
    )


async def reset_rate_limits() -> None:
    """Drop the `rl:*` counters.

    Lockout and rate limiting are two different controls over the same event
    (P§7 step 5): one is per account and durable, the other per attempt and
    ephemeral. A test aimed at one has to silence the other, or it measures
    whichever trips first.
    """
    async for key in cache._client.scan_iter("rl:*"):
        await cache._client.delete(key)


def drop_entry(path: Path, numero_fiscal: str) -> None:
    """Make an entry vanish from the directory, the way a real one would."""
    import json

    entries = json.loads(path.read_text(encoding="utf-8"))
    path.write_text(
        json.dumps([e for e in entries if e["numero_fiscal"] != numero_fiscal], ensure_ascii=False),
        encoding="utf-8",
    )
