from pydantic import BaseModel
from pydantic import Field
from pydantic import ValidationError
from pydantic import field_validator
from fastapi import Request
from fastapi import Depends
from fastapi.responses import RedirectResponse
from typing import Literal
from urllib.parse import urlencode

from . import router
from authentint.config import settings
from authentint.clients import queries as clients
from authentint.infra.models.identity import User
from authentint.infra.models.identity import UserStatus
from authentint.infra.database import get_session
from authentint.sessions.queries import from_cookie
from authentint.domain.errors import error_page
from authentint.domain.errors import redirect_error
from authentint.oidc.codes import issue_code
from authentint.domain.scopes import grant
from authentint.audit import audit
from authentint.flows import consent as consents
from authentint.flows import interaction


class AuthorizeParams(BaseModel):
    response_type: Literal["code"]
    client_id: str
    redirect_uri: str
    # Bounded: state and nonce are stored in interactions and echoed back, a megabyte of either is not a request
    scope: str = Field(max_length=1024)
    state: str = Field(min_length=1, max_length=512)
    nonce: str = Field(min_length=1, max_length=512)
    code_challenge: str = Field(pattern=r"^[A-Za-z0-9_-]{43}$")  # RFC 7636 §4.2: BASE64URL(SHA256) is always 43 chars
    code_challenge_method: Literal["S256"]

    @field_validator("scope")
    @classmethod
    def needs_openid(cls, value: str) -> str:
        if "openid" not in value.split():
            raise ValueError("scope must include openid")

        return value


@router.get("/authorize")
async def authorize(request: Request, session=Depends(get_session)):
    query = request.query_params
    client = await clients.get(session, query.get("client_id"))

    if client is None or query.get("redirect_uri") not in client.redirect_uris:
        return error_page("invalid_client")

    try:
        params = AuthorizeParams(**query)
    except ValidationError:
        # Handling error with ?error=...&state=... redirects
        return redirect_error(query["redirect_uri"], "invalid_request", query.get("state"))

    sso = await from_cookie(session, request) # Does an SSO cookie exist?

    if sso is None:
        it = await interaction.create(session, params)

        return RedirectResponse(f"{settings.public_base_url}/login?uid={it.uid}", 302)

    user = await session.get(User, sso.user_id)

    if user is None or user.status != UserStatus.active:
        return redirect_error(params.redirect_uri, "access_denied", params.state)

    requested = set(params.scope.split())
    granted = grant(requested, user.role, client)

    if granted != requested:
        await audit.emit(session, "authorize.scope_reduced", actor=user.id, outcome="success", detail={"requested": sorted(requested), "granted": sorted(granted)})

    # ADR §10 step 9: a live session is not consent. Without this, any client requiring consent
    # would get a code for a logged-in user who never agreed, just by sending them here.
    if client.require_consent and not await consents.covers(session, user.id, client.id, granted):
        it = await interaction.create(session, params, user_id=user.id)  # known user: the first step is consent

        return RedirectResponse(f"{settings.public_base_url}/login?uid={it.uid}", 302)

    oauth_auth_code = await issue_code(session, params, sso, " ".join(sorted(granted)))
    redirect_url = f"{params.redirect_uri}{"&" if "?" in params.redirect_uri else "?"}{urlencode({"code": oauth_auth_code, "state": params.state})}"

    return RedirectResponse(redirect_url, 302)
