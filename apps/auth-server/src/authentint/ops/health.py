"""
Kubernetes probes (ADR §9 Ops). They answer different questions, and mixing them up hurts:

- live:  "is this process stuck?" A failure makes Kubernetes RESTART the pod.
         Never check a dependency here: Postgres down would restart every replica in a loop.
- ready: "can this replica serve requests right now?" A failure only takes the pod OUT of
         the Service until it recovers. This is where dependencies are checked.
"""

from fastapi import Depends
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from . import router
from authentint.infra.database import get_session


@router.get("/health/live")
async def live():
    return {"status": "ok"}

@router.get("/health/ready")
async def ready(session: AsyncSession = Depends(get_session)):
    # TODO(human)
    return JSONResponse({"status": "ok"})
