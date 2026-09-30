"""
Interaction API (ADR §9): the frontend drives the steps of one pending /authorize.

The `uid` is an opaque handle to server-side state: client_id, scope and redirect_uri
never travel through the browser, so they can't be tampered with. The server alone
decides the next step (`next_step`); the client is never trusted on where it stands.

B0 freezes the request/response shapes below: they are exported to
docs/generated/openapi.json, which the frontend mocks (seam S3).
`login` and `consent` belong to B1 and answer 501 until then.
"""

import secrets

from datetime import UTC
from datetime import datetime
from datetime import timedelta
from typing import Literal
from urllib.parse import urlencode

from fastapi import Depends
from fastapi import HTTPException
from pydantic import BaseModel
from pydantic import Field
from sqlalchemy import func
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from . import router
from authentint.config import settings
from authentint.clients import queries as clients
from authentint.infra.database import get_session
from authentint.infra.models.oauth import OAuthClients
from authentint.infra.models.oauth import OAuthInteractions


TTL = timedelta(minutes=10)

Prompt = Literal["login", "consent"]  # the MFA seam (ADR §2) will add "otp"


class InteractionView(BaseModel):
    prompt: Prompt | None = Field(description="Step to display next. null: finished, follow redirect_to")
    client_name: str
    scopes: list[str]
    redirect_to: str | None = Field(None, description="Set when prompt is null: back to /authorize, which issues the code")

class LoginBody(BaseModel):
    numero_fiscal: str = Field(pattern=r"^\d{13}$")
    password: str = Field(min_length=1, max_length=1024)

class ConsentBody(BaseModel):
    approve: bool


async def create(session: AsyncSession, params) -> OAuthInteractions:
    """Called by /authorize (oidc/) when there is no SSO session. `params` is its validated AuthorizeParams."""

    it = OAuthInteractions(
        uid=secrets.token_urlsafe(32), client_id=params.client_id, redirect_uri=params.redirect_uri,
        scope=params.scope, state=params.state, nonce=params.nonce, code_challenge=params.code_challenge,
        code_challenge_method=params.code_challenge_method, stage="login", expires_at=datetime.now(UTC) + TTL,
    )
    session.add(it)
    await session.commit()

    return it

async def load(session: AsyncSession, uid: str) -> OAuthInteractions:
    it = await session.scalar(select(OAuthInteractions).where(OAuthInteractions.uid == uid, OAuthInteractions.expires_at > func.now()))

    if it is None:
        raise HTTPException(404, "unknown_interaction")  # same answer for unknown and expired

    return it

def next_step(it: OAuthInteractions, client: OAuthClients) -> Prompt | None:
    if it.user_id is None:
        return "login"
    # B1: `if needs_otp: return "otp"` goes here, then skip consent when a consents row already covers it.scope
    if client.require_consent:
        return "consent"
    return None

def resume_url(it: OAuthInteractions) -> str:
    """The original /authorize request, rebuilt from server-side state: the session cookie now exists, so it takes the SSO path."""

    return f"{settings.issuer}/authorize?" + urlencode({
        "response_type": "code", "client_id": it.client_id, "redirect_uri": it.redirect_uri, "scope": it.scope,
        "state": it.state, "nonce": it.nonce, "code_challenge": it.code_challenge,
        "code_challenge_method": it.code_challenge_method,
    })

async def view(session: AsyncSession, it: OAuthInteractions) -> InteractionView:
    client = await clients.get(session, it.client_id)
    prompt = next_step(it, client)

    return InteractionView(prompt=prompt, client_name=client.name, scopes=it.scope.split(),
                           redirect_to=resume_url(it) if prompt is None else None)


@router.get("/interaction/{uid}", response_model=InteractionView, responses={404: {"description": "Unknown or expired uid"}})
async def get_interaction(uid: str, session: AsyncSession = Depends(get_session)):
    return await view(session, await load(session, uid))

@router.post("/interaction/{uid}/login", response_model=InteractionView, status_code=200, responses={
    401: {"description": "Bad numero_fiscal or password (same answer for both)"},
    404: {"description": "Unknown or expired uid"},
    423: {"description": "Account locked"},
    429: {"description": "Rate limited"},
    501: {"description": "Not built yet (B1)"},
})
async def login(uid: str, body: LoginBody, session: AsyncSession = Depends(get_session)):
    """On success, sets the `__Host-session` cookie and answers the next step."""

    raise HTTPException(501, "B1: password check, lockout, rate limit, sessions.create")

@router.post("/interaction/{uid}/consent", response_model=InteractionView, responses={
    404: {"description": "Unknown or expired uid"},
    501: {"description": "Not built yet (B1)"},
})
async def consent(uid: str, body: ConsentBody, session: AsyncSession = Depends(get_session)):
    """approve=false ends the flow: redirect_to then carries error=access_denied."""

    raise HTTPException(501, "B1: store the consents row, or end with access_denied")
