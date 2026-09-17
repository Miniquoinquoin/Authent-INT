"""The provisioning feed. Brick B7's definition of done is in here (§16)."""

from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.directory import FixtureDirectory
from app.models import Role, Status, User
from app.sync import run
from helpers import drop_entry

TRANSIENT = "1806234567896"  # Théo Roussel — the entry that disappears
NO_GROUPS = "1805234567895"  # Hugo Petit — the entry missing an optional attribute
ADMIN = "1801234567891"


async def sync(path: Path, db: AsyncSession):
    return await run(FixtureDirectory(path), db)


async def test_first_run_creates_every_entry_pending_activation(fixture_file, db):
    report = await sync(fixture_file, db)

    assert (report.created, report.updated, report.disabled) == (6, 0, 0)
    users = (await db.scalars(select(User))).all()
    assert len(users) == 6
    # The directory is read-only, so it cannot supply a password. Every account
    # arrives needing activation (§5b).
    assert {u.status for u in users} == {Status.PENDING_ACTIVATION}
    assert {u.password_hash for u in users} == {None}


async def test_second_run_changes_nothing(fixture_file, db):
    await sync(fixture_file, db)
    before = {u.external_id: (u.nom, u.prenom, u.email, u.role, u.status, u.updated_at) for u in (await db.scalars(select(User))).all()}

    report = await sync(fixture_file, db)

    assert (report.created, report.updated, report.disabled) == (0, 0, 0)
    db.expire_all()
    after = {u.external_id: (u.nom, u.prenom, u.email, u.role, u.status, u.updated_at) for u in (await db.scalars(select(User))).all()}
    assert after == before, "a second sync must not touch user data"


async def test_vanished_entry_is_disabled_never_deleted(fixture_file, db):
    await sync(fixture_file, db)
    drop_entry(fixture_file, TRANSIENT)

    report = await sync(fixture_file, db)

    assert report.disabled == 1
    gone = await db.scalar(select(User).where(User.numero_fiscal == TRANSIENT))
    assert gone is not None, "a transient directory error must never empty the user base"
    assert gone.status is Status.DISABLED


async def test_reappearing_entry_is_restored(fixture_file, db):
    await sync(fixture_file, db)
    drop_entry(fixture_file, TRANSIENT)
    await sync(fixture_file, db)

    # Put it back, exactly as the directory would.
    import json
    entries = json.loads(fixture_file.read_text(encoding="utf-8"))
    entries.append({
        "external_id": "b3f1c8de-0000-4a10-9c31-000000000006",
        "numero_fiscal": TRANSIENT,
        "nom": "Roussel", "prenom": "Théo",
        "email": "theo.roussel@contribuable.example",
        "groups": ["cn=contribuables,ou=groupes,dc=dgfip,dc=local"],
    })
    fixture_file.write_text(json.dumps(entries, ensure_ascii=False), encoding="utf-8")

    await sync(fixture_file, db)

    db.expire_all()
    back = await db.scalar(select(User).where(User.numero_fiscal == TRANSIENT))
    assert back.status is Status.PENDING_ACTIVATION, "never activated, so it returns needing activation"


async def test_group_dn_maps_to_role_and_defaults_to_least_privilege(fixture_file, db):
    await sync(fixture_file, db)

    admin = await db.scalar(select(User).where(User.numero_fiscal == ADMIN))
    ungrouped = await db.scalar(select(User).where(User.numero_fiscal == NO_GROUPS))
    assert admin.role is Role.ADMIN
    # §17 Q6 has not come back: an unmapped entry gets the least privilege, not a guess.
    assert ungrouped.role is Role.CONTRIBUABLE


async def test_accented_attributes_survive_the_round_trip(fixture_file, db):
    await sync(fixture_file, db)

    names = {u.prenom for u in (await db.scalars(select(User))).all()}
    assert {"Aurélien", "Inês", "Théo"} <= names


async def test_attribute_change_updates_the_row(fixture_file, db):
    await sync(fixture_file, db)
    import json
    entries = json.loads(fixture_file.read_text(encoding="utf-8"))
    for e in entries:
        if e["numero_fiscal"] == ADMIN:
            e["nom"] = "Marchand-Dubois"
    fixture_file.write_text(json.dumps(entries, ensure_ascii=False), encoding="utf-8")

    report = await sync(fixture_file, db)

    assert report.updated == 1
    db.expire_all()
    user = await db.scalar(select(User).where(User.numero_fiscal == ADMIN))
    assert user.nom == "Marchand-Dubois"


async def test_an_empty_feed_disables_nobody(fixture_file, db):
    """An empty feed is a directory outage, not a directory with no users.
    Disabling everyone would lock the user base out as surely as deleting it."""
    await sync(fixture_file, db)
    fixture_file.write_text("[]", encoding="utf-8")

    report = await sync(fixture_file, db)

    assert (report.seen, report.disabled) == (0, 0)
    db.expire_all()
    statuses = {u.status for u in (await db.scalars(select(User))).all()}
    assert statuses == {Status.PENDING_ACTIVATION}, "nobody was touched"
