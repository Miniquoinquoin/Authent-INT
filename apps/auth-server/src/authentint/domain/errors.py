"""
Defines how OAuth errors (described at RFC 6749 §4.1.2.1) should be dealt with.

Some company would change these behaviour such that "OK" is sent to the user's client to prevent certains attacks but this is out of scope
"""

import html

from typing import Literal
from urllib.parse import urlencode
from fastapi.responses import JSONResponse
from fastapi.responses import RedirectResponse
from fastapi.responses import HTMLResponse


# The only `error=` values the server may emit: RFC 6749 §4.1.2.1 (/authorize) and §5.2 (/token)
AuthorizeErrorCode = Literal["invalid_request", "unauthorized_client", "access_denied", "unsupported_response_type",
                             "invalid_scope", "server_error", "temporarily_unavailable"]
TokenErrorCode = Literal["invalid_request", "invalid_client", "invalid_grant", "unauthorized_client",
                         "unsupported_grant_type", "invalid_scope"]


class OAuthError(Exception):
    """Raised by /token, /revoke…: answered as a JSON 400 by oauth_error_handler."""

    def __init__(self, error: TokenErrorCode) -> None:
        self.error = error

async def oauth_error_handler(request, err: OAuthError):
    return JSONResponse({"error": err.error}, status_code=400)

def redirect_error(redirect_uri: str, error: AuthorizeErrorCode, state: str | None) -> RedirectResponse:
    return RedirectResponse(f"{redirect_uri}{"&" if "?" in redirect_uri else "?"}{urlencode({'error': error, 'state': state or ''})}", 302)

def error_page(error: str) -> HTMLResponse:
    """
    Mocking an error page to redirect to after an OAuth error is catched
    """

    return HTMLResponse(f"<h1>Erreur : {html.escape(error)}</h1>", status_code=400)
