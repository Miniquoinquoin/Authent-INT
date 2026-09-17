"""The provisioning feed: directory → `users`. `python -m app.sync`.

The **only** module that imports both `directory` and `models`. That single join
point is what makes §5b's "no request handler ever talks to the directory" true
by construction rather than by discipline (§10, boundary 4) — and it is exactly
seam S5.

Never runs inside a request. In k8s it becomes a CronJob (§5b).
"""

import asyncio
import logging
from dataclasses import asdict, dataclass
from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.directory import DirectoryUser, FixtureDirectory, UserDirectory
from app.infra.db import SessionLocal, engine
from app.models import Role, Status, User

log = logging.getLogger(__name__)

#: Most privilege wins when an entry sits in several mapped groups.
ROLE_PRECEDENCE = (Role.ADMIN, Role.AGENT, Role.CONTRIBUABLE)


@dataclass
class Report:
    created: int = 0
    updated: int = 0
    disabled: int = 0
    seen: int = 0


def role_for(groups: list[str]) -> Role:
    """Group DN → role, from configuration and never from code (§5b).

    The real mapping is §17 Q6 and has not come back, so an unmapped entry gets
    the least-privileged role rather than a guess.
    """
    mapping = settings().group_role_map
    mapped = {mapping[dn] for dn in groups if dn in mapping}
    for role in ROLE_PRECEDENCE:
        if role.value in mapped:
            return role
    return Role(settings().default_role)


def _desired(entry: DirectoryUser) -> dict[str, object]:
    """The attributes the directory owns. Everything else is ours (§5b)."""
    return {
        "numero_fiscal": entry.numero_fiscal,
        "email": str(entry.email),
        "nom": entry.nom,
        "prenom": entry.prenom,
        "role": role_for(entry.groups),
    }


async def run(directory: UserDirectory, db: AsyncSession) -> Report:
    report = Report()
    now = datetime.now(UTC)
    seen: set[str] = set()

    async for entry in directory.list():
        seen.add(entry.external_id)
        report.seen += 1

        user = await db.scalar(select(User).where(User.external_id == entry.external_id))
        desired = _desired(entry)

        if user is None:
            db.add(
                User(
                    external_id=entry.external_id,
                    status=Status.PENDING_ACTIVATION,
                    password_hash=None,
                    synced_at=now,
                    **desired,
                )
            )
            report.created += 1
            continue

        changes = {k: v for k, v in desired.items() if getattr(user, k) != v}
        if user.status is Status.DISABLED:
            # The entry came back. Restore it to whatever it was before the
            # directory dropped it: activated accounts keep their password.
            changes["status"] = Status.ACTIVE if user.password_hash else Status.PENDING_ACTIVATION
        if changes:
            for field, value in changes.items():
                setattr(user, field, value)
            user.updated_at = now
            report.updated += 1
        user.synced_at = now

    # Never deletes. A vanished entry is disabled, because a transient directory
    # error must not be able to empty the user base (§5b).
    vanished = await db.execute(
        update(User)
        .where(
            User.external_id.is_not(None),
            User.external_id.not_in(seen) if seen else User.external_id.is_not(None),
            User.status != Status.DISABLED,
        )
        .values(status=Status.DISABLED, updated_at=now)
    )
    report.disabled = vanished.rowcount or 0

    await db.commit()
    log.info(
        "sync.completed",
        extra={"event": {"event_type": "sync.completed", "outcome": "success", **asdict(report)}},
    )
    return report


async def main() -> None:
    from app.main import LOGGING  # log config lives with the app factory (§10)
    import logging.config

    logging.config.dictConfig(LOGGING)
    directory = FixtureDirectory(settings().fixture_file)
    async with SessionLocal() as db:
        await run(directory, db)
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
