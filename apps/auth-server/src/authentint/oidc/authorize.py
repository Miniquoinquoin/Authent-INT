from pydantic import BaseModel
from pydantic import ValidationError
from pydantic import field_validator
from fastapi import Request
from fastapi import Depends
from fastapi.responses import RedirectResponse
from typing import Literal

from . import router
from authentint.config import settings
from authentint.clients import queries as clients
from authentint.infra.database import get_session
from authentint.sessions.queries import from_cookie
from authentint.domain.errors import error_page
from authentint.domain.errors import redirect_error
from authentint.oidc.codes import issue_code
from authentint.flows import interaction


class AuthorizeParams(BaseModel):
    response_type: Literal["code"]
    client_id: str
    redirect_uri: str
    scope: str
    state: str
    nonce: str
    code_challenge: str
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

    return await issue_code(session, params, sso)
