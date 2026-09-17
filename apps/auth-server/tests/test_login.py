"""Password login: the five failure branches, lockout, and what gets logged."""

import json
import statistics
import time

import pytest
from sqlalchemy import select

from app.config import settings
from app.models import Status, User
from helpers import (
    ADMIN_NF,
    AGENT_NF,
    PASSWORD,
    TRANSIENT_NF,
    activate_directly,
    drop_entry,
    login,
    reset_rate_limits,
    seed,
)


@pytest.fixture(autouse=True)
async def users(db, fixture_file):
    await seed(db, fixture_file)


async def test_happy_path_advances_to_mfa(client, db):
    await activate_directly(db, ADMIN_NF)

    response = await login(client, ADMIN_NF)

    assert response.status_code == 200
    assert response.json() == {"stage": "mfa"}


async def test_all_five_failure_branches_are_byte_identical(client, db, fixture_file):
    """Unknown, wrong password, awaiting activation, locked, disabled.

    Not "similar" — identical bytes. That is what makes the property structural
    rather than a promise somebody has to keep in a sixth handler (§10).
    """
    await activate_directly(db, ADMIN_NF)

    # locked
    locked = await db.scalar(select(User).where(User.numero_fiscal == AGENT_NF))
    locked.status = Status.LOCKED
    locked.password_hash = None
    await db.commit()

    # disabled, the way §5's sync writes it: the entry left the directory
    drop_entry(fixture_file, TRANSIENT_NF)
    await seed(db, fixture_file)

    bodies, codes = set(), set()
    for nf, password in [
        ("0000000000000", PASSWORD),      # unknown
        (ADMIN_NF, "le mauvais mot de passe"),  # wrong password
        ("1803234567893", PASSWORD),      # pending_activation
        (AGENT_NF, PASSWORD),             # locked
        (TRANSIENT_NF, PASSWORD),         # disabled
    ]:
        response = await login(client, nf, password)
        bodies.add(response.content)
        codes.add(response.status_code)

    assert len(bodies) == 1, "five branches, one answer"
    assert codes == {401}


async def test_unknown_user_costs_what_a_known_one_costs(client, db):
    """The response body says nothing; the clock must not say more.

    An unknown numéro fiscal still pays for an Argon2 verification, against a
    dummy hash. Without that, a stopwatch is the enumeration oracle.
    """
    await activate_directly(db, ADMIN_NF)

    async def timed(nf: str, password: str) -> float:
        # The limiter would otherwise answer 429 without touching Argon2, and
        # the sample would time the limiter instead of the crypto.
        await reset_rate_limits()
        start = time.perf_counter()
        response = await login(client, nf, password)
        assert response.status_code == 401
        return time.perf_counter() - start

    unknown = statistics.median([await timed("0000000000000", PASSWORD) for _ in range(7)])
    known = statistics.median([await timed(ADMIN_NF, "le mauvais mot de passe") for _ in range(7)])

    ratio = max(unknown, known) / min(unknown, known)
    assert ratio < 2.0, f"timing distributions must overlap; ratio was {ratio:.2f}"


async def test_disabled_user_is_refused_and_no_mail_is_sent(client, db, fixture_file, inbox):
    """The disable-never-delete rule of §5b, enforced where it matters.

    A vanished directory entry that could still log in would make the sync job
    decorative. And a disabled account gets no activation mail: only the
    pending branch mails anything (P§7 step 6).
    """
    drop_entry(fixture_file, TRANSIENT_NF)
    await seed(db, fixture_file)

    response = await login(client, TRANSIENT_NF)

    assert response.status_code == 401
    gone = await db.scalar(select(User).where(User.numero_fiscal == TRANSIENT_NF))
    assert gone.status is Status.DISABLED
    assert inbox.count() == 0


async def test_pending_activation_mails_a_link(client, db, inbox):
    """The login attempt is the trigger — there is no /activation/request to
    probe for account existence (P§6)."""
    response = await login(client, ADMIN_NF)

    assert response.status_code == 401
    assert inbox.count() == 1
    assert "/activer?token=" in inbox.latest_body()


async def test_lockout_after_n_failures_holds_against_the_right_password(client, db):
    await activate_directly(db, ADMIN_NF)
    limit = settings().login_max_failures

    for _ in range(limit):
        await reset_rate_limits()
        assert (await login(client, ADMIN_NF, "mauvais mot de passe")).status_code == 401

    db.expire_all()
    user = await db.scalar(select(User).where(User.numero_fiscal == ADMIN_NF))
    assert user.status is Status.LOCKED
    assert user.locked_until is not None

    # The point of a lockout: the correct password does not release it. The
    # rate limiter is cleared first so the 401 below is the lock talking.
    await reset_rate_limits()
    assert (await login(client, ADMIN_NF, PASSWORD)).status_code == 401


async def test_expired_lockout_reads_as_unlocked(client, db):
    """There is no unlock job. A `locked_until` in the past simply passes."""
    from datetime import UTC, datetime, timedelta

    await activate_directly(db, ADMIN_NF)
    user = await db.scalar(select(User).where(User.numero_fiscal == ADMIN_NF))
    user.status = Status.LOCKED
    user.locked_until = datetime.now(UTC) - timedelta(minutes=1)
    await db.commit()

    response = await login(client, ADMIN_NF)

    assert response.json() == {"stage": "mfa"}


async def test_a_failed_login_logs_one_line_without_the_numero_fiscal(client, db, caplog_json):
    """§1 defers `audit_events` *because* these lines exist, and §5 puts the
    numéro fiscal in the same class as a password. Both claims are tested here
    or they are not true."""
    await activate_directly(db, ADMIN_NF)
    caplog_json.clear()

    await login(client, ADMIN_NF, "mauvais mot de passe")

    from app.main import JsonFormatter

    formatter = JsonFormatter()
    lines = [json.loads(formatter.format(r)) for r in caplog_json.records if r.name.startswith("app.")]
    failures = [line for line in lines if line.get("event_type") == "login.failure"]
    assert len(failures) == 1
    assert failures[0]["outcome"] == "failure"
    assert failures[0]["request_id"]

    blob = json.dumps(lines, ensure_ascii=False)
    assert ADMIN_NF not in blob
    assert "mauvais mot de passe" not in blob


async def test_rate_limit_trips_per_account(client, db):
    """Per account, separately from per IP (§15). Both are in the flow; this
    exercises the account counter by holding the IP constant."""
    await activate_directly(db, ADMIN_NF)
    cfg = settings()
    budget = min(cfg.rl_login_ip, cfg.rl_login_account)

    codes = [(await login(client, ADMIN_NF, "mauvais")).status_code for _ in range(budget + 2)]

    assert 429 in codes, "the limiter must eventually say no"
    assert codes[-1] == 429


async def test_valkey_down_rejects_the_login(client, db, monkeypatch):
    """**Fails closed** (§11b rule 3).

    Failing open would remove brute-force protection at precisely the moment
    something is going wrong. The container is stopped for real in the
    end-to-end check; here the client raises so the assertion runs in CI.
    """
    from redis.exceptions import ConnectionError as RedisConnectionError

    from app.infra import cache

    await activate_directly(db, ADMIN_NF)

    def dead(*_args, **_kwargs):
        raise RedisConnectionError("valkey is down")

    # The limiter is the first thing the login touches, and it goes through a
    # pipeline; failing its construction is what a dead socket looks like.
    monkeypatch.setattr(cache._client, "pipeline", dead)

    response = await login(client, ADMIN_NF)

    assert response.status_code == 503, "rejected, not allowed"
