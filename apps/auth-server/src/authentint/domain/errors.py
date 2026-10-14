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
from fastapi.exception_handlers import request_validation_exception_handler


# The only `error=` values the server may emit: RFC 6749 §4.1.2.1 (/authorize) and §5.2 (/token)
AuthorizeErrorCode = Literal["invalid_request", "unauthorized_client", "access_denied", "unsupported_response_type",
                             "invalid_scope", "server_error", "temporarily_unavailable"]
# What /token accepts (oidc/token.py has one body per grant) and discovery advertises
GRANT_TYPES = ("authorization_code", "refresh_token")
TokenErrorCode = Literal["invalid_request", "invalid_client", "invalid_grant", "unauthorized_client",
                         "unsupported_grant_type", "invalid_scope"]


class OAuthError(Exception):
    """Raised by /token, /revoke…: answered as a JSON 400 by oauth_error_handler."""

    def __init__(self, error: TokenErrorCode) -> None:
        self.error = error

async def oauth_error_handler(request, err: OAuthError):
    return JSONResponse({"error": err.error}, status_code=400)

async def token_validation_handler(request, exc) -> JSONResponse:
    # Every route other than /token and /revoke (RFC 7009 §2.2.1 reuses §5.2) goes to FastAPI's default handler (keeping their 422)
    if request.url.path not in ("/token", "/revoke"):
        return await request_validation_exception_handler(request, exc)

    code = "invalid_request"

    # A MISSING grant_type is a missing parameter (invalid_request); only an unknown value is unsupported.
    # Checked on the value: the body is a union, so a refresh request also fails the code body's grant_type literal
    if any("grant_type" in e["loc"] and e["type"] != "missing" and e["input"] not in GRANT_TYPES for e in exc.errors()):
        code = "unsupported_grant_type"

    return JSONResponse({"error": code}, headers={"Cache-Control": "no-store"}, status_code=400)

def error_url(redirect_uri: str, error: AuthorizeErrorCode, state: str | None) -> str:
    """The client's redirect_uri carrying error= and state= (RFC 6749 §4.1.2.1)."""

    return f"{redirect_uri}{"&" if "?" in redirect_uri else "?"}{urlencode({'error': error, 'state': state or ''})}"

def redirect_error(redirect_uri: str, error: AuthorizeErrorCode, state: str | None) -> RedirectResponse:
    return RedirectResponse(error_url(redirect_uri, error, state), 302)

def error_page(error: str) -> HTMLResponse:
    """
    Mocking an error page to redirect to after an OAuth error is catched
    """

    return HTMLResponse(f"<h1>Erreur : {html.escape(error)}</h1>", status_code=400)
