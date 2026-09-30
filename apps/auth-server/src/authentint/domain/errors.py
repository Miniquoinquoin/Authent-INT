"""
Defines how OAuth errors (described at RFC 6749 §4.1.2.1) should be dealt with.

Some company would change these behaviour such that "OK" is sent to the user's client to prevent certains attacks but this is out of scope
"""

import html

from urllib.parse import urlencode
from fastapi.responses import JSONResponse
from fastapi.responses import RedirectResponse
from fastapi.responses import HTMLResponse


class OAuthError(Exception):
    """"""

    def __init__(self, error: str) -> None:
        self.error = error

async def oauth_error_handler(request, err: OAuthError):
    return JSONResponse({"error": err.error}, status_code=400)

def redirect_error(redirect_uri: str, error: str, state: str | None) -> RedirectResponse:
    return RedirectResponse(f"{redirect_uri}{"&" if "?" in redirect_uri else "?"}{urlencode({'error': error, 'state': state or ''})}", 302)

def error_page(error: str) -> HTMLResponse:
    """
    Mocking an error page to redirect to after an OAuth error is catched
    """

    return HTMLResponse(f"<h1>Erreur : {html.escape(error)}</h1>", status_code=400)
