"""
/end-session (OIDC RP-Initiated Logout 1.0): the application sends the user here to log out.

Same rule as /authorize (ADR §10): the return address must be one the client registered, compared
exactly, or there is no redirect at all. Otherwise this would be an open redirector on our domain.
id_token_hint is ignored: the SPA sends none, and the session cookie already says who logs out.
"""

from urllib.parse import urlencode

from fastapi import Depends
from fastapi import Request
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from . import router
from authentint.audit import audit
from authentint.clients import queries as clients
from authentint.domain.errors import error_page
from authentint.infra.database import get_session
from authentint.oidc import refresh
from authentint.sessions.queries import from_cookie


@router.get("/end-session")
async def end_session(request: Request, session: AsyncSession = Depends(get_session)):
    query = request.query_params
    client = await clients.get(session, query.get("client_id"))
    uri = query.get("post_logout_redirect_uri")

    if client is None or uri not in client.post_logout_redirect_uris:
        return error_page("invalid_request")

    sso = await from_cookie(session, request)

    if sso is not None:
        await refresh.revoke_session(session, sso.id, "logout")  # its refresh tokens too: logout means logged out everywhere it reached
        await audit.emit(session, "logout", actor=sso.user_id, outcome="success", detail={"sid": str(sso.id), "client_id": client.id})
        await session.commit()

    state = query.get("state")
    location = uri if state is None else f"{uri}{"&" if "?" in uri else "?"}{urlencode({"state": state})}"
    response = RedirectResponse(location, 302)
    # whatever the cookie held (live, revoked, garbage): the browser forgets it. Same attributes as when set
    response.delete_cookie("__Host-session", path="/", secure=True, httponly=True, samesite="lax")

    return response
