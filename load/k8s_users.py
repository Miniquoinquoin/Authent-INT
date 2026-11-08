"""Create or disable the load test's accounts on a cluster. See docs/load-report.md.

load/ isn't in the image, so this is piped into a pod, with its settings prepended on stdin:

    { echo "ACTION='create'; PASSWORD='...'"; cat load/k8s_users.py; } | kubectl exec -i deploy/auth-server -c auth-server -- python -
    { echo "ACTION='disable'"; cat load/k8s_users.py; } | kubectl exec -i deploy/auth-server -c auth-server -- python -

`disable` keeps the rows: the audit log refers to them and is append-only.
"""

import asyncio

from sqlalchemy import func
from sqlalchemy import select
from sqlalchemy import update
from sqlalchemy.dialects.postgresql import insert

from authentint.infra.database import Session
from authentint.infra.models.identity import Role
from authentint.infra.models.identity import User
from authentint.infra.models.identity import UserStatus
from authentint.security.identifiers import numero_fiscal_digest
from authentint.security.passwords import hash_password

COUNT = 200
FIRST_NUMBER = 1910000000000  # no fixture or example account uses this range
LOADTEST = User.external_id.like("loadtest-%")


async def create(session) -> None:
    password_hash = await hash_password(PASSWORD)  # noqa: F821 (prepended on stdin)
    for i in range(COUNT):
        await session.execute(insert(User).values(
            external_id=f"loadtest-{i}", numero_fiscal_hmac=numero_fiscal_digest(str(FIRST_NUMBER + i)),
            email=f"loadtest-{i}@authentint.example", nom="Loadtest", prenom=str(i), role=Role.contribuable,
            status=UserStatus.active, password_hash=password_hash, password_changed_at=func.now(),
        ).on_conflict_do_nothing())


async def disable(session) -> None:
    await session.execute(update(User).where(LOADTEST).values(status=UserStatus.disabled, password_hash=None))


async def main() -> None:
    async with Session() as session:
        await {"create": create, "disable": disable}[ACTION](session)  # noqa: F821 (prepended on stdin)
        await session.commit()
        rows = await session.execute(select(User.status, func.count()).where(LOADTEST).group_by(User.status))
        print({status.value: count for status, count in rows})


asyncio.run(main())
