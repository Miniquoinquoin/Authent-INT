"""
Kubernetes probes (ADR §9 Ops). They answer different questions, and mixing them up hurts:

- live:  "is this process stuck?" A failure makes Kubernetes RESTART the pod.
         Never check a dependency here: Postgres down would restart every replica in a loop.
- ready: "can this replica serve requests right now?" A failure only takes the pod OUT of
         the Service until it recovers. This is where dependencies are checked.
"""

from fastapi import Depends
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from . import router
from authentint.infra.database import get_session
from authentint.infra.models.keys import KeyStatus
from authentint.infra.models.keys import SigningKeys


@router.get("/health/live")
async def live():
    return {"status": "ok"}

@router.get("/health/ready")
async def ready(session: AsyncSession = Depends(get_session)):
    # Step 1: can this replica talk to Postgres?
    try:
        await session.execute(text("SELECT 1"))

        # Step 2: is there an active signing key? Without one, /token cannot sign any token.
        key = await session.scalar(select(SigningKeys).where(SigningKeys.status == KeyStatus.active))

    except Exception:
        # Postgres is down or unreachable: "not ready", never a 500 with a stack trace
        return JSONResponse({"status": "unavailable", "reason": "database"}, status_code=503)

    if key is None:
        return JSONResponse({"status": "unavailable", "reason": "no_active_key"}, status_code=503)

    return {"status": "ok"}
