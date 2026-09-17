"""`/me` and `/logout`. Cookie-authenticated — and only for now.

Both become Bearer-protected at B2, where the session lookup below turns into
§8 step 6, the SSO check. Nothing else about them changes.
"""

import logging

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app import sessions
from app.infra.db import get_db
from app.models import Session, User
from app.schemas import Failure, Me, refuse

log = logging.getLogger(__name__)
router = APIRouter(tags=["me"])

NO_SESSION = Failure(detail="Non authentifié.")


async def current(request: Request, db: AsyncSession = Depends(get_db)) -> tuple[Session, User] | None:
    return await sessions.resolve(db, sessions.read_cookie(request))


@router.get("/me", response_model=Me)
async def me(found: tuple[Session, User] | None = Depends(current)) -> Me | JSONResponse:
    """What the session resolves to. The proof the cookie works end to end."""
    if found is None:
        return refuse(NO_SESSION)
    session, user = found
    return Me(
        nom=user.nom,
        prenom=user.prenom,
        role=user.role.value,
        statut=user.status.value,
        session_ouverte_a=session.created_at,
    )


@router.post("/logout", status_code=204)
async def logout(
    response: Response,
    found: tuple[Session, User] | None = Depends(current),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Revoke the row, then clear the cookie.

    Revoking first matters: the cookie is a hint, the row is the truth. Clearing
    only the cookie would leave a live session for anyone who kept a copy.
    """
    if found is not None:
        session, _ = found
        await sessions.revoke(db, session, reason="logout")
    sessions.clear_cookie(response)
    response.status_code = 204
    return response
