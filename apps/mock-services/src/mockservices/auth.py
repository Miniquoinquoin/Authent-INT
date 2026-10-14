"""
Access token verification (ADR §11, docs/architecture.md §3). Every check blocks a real attack:

    alg pinned to RS256   alg:none, and HS256 signed with the public key as HMAC secret
    typ at+jwt            an ID token (or any other JWT from the same issuer) used as an access token
    iss                   a genuine token from another OpenID Provider
    aud                   a token for svc-cadastre replayed on svc-impots
    exp                   replay of an old, stolen token
    scope                 authenticated, but not allowed here (403, not 401)

Authorisation is enforced HERE, never only in the frontend (invariant 12).
"""

import logging
from typing import Annotated, Any

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from joserfc import jws, jwt
from joserfc.errors import JoseError

from mockservices.config import Settings
from mockservices.jwks import JwksClient, JwksUnavailable


log = logging.getLogger(__name__)

# RFC 9068 §4: typ is "at+jwt"; the "application/" prefix may be spelled out (RFC 7515 §4.1.9)
ACCESS_TOKEN_TYPES = {"at+jwt", "application/at+jwt"}


class InvalidToken(Exception):
    pass


class Verifier:
    def __init__(self, settings: Settings, jwks: JwksClient):
        self.jwks = jwks
        self.claims = jwt.JWTClaimsRegistry(
            leeway=settings.leeway,
            iss={"essential": True, "value": settings.issuer},
            aud={"essential": True, "value": settings.audience},  # aud is a list: must CONTAIN us
            exp={"essential": True},
            iat={"essential": True},  # nbf and iat are also refused if in the future
            sub={"essential": True},
            scope={"essential": True},
        )

    async def verify(self, token: str) -> dict[str, Any]:
        try:
            header = jws.extract_compact(token.encode()).headers()
        except (JoseError, ValueError) as exc:
            raise InvalidToken(f"malformed: {exc!r}")

        # Read from the header only to pick a key and reject the wrong token kind, never to choose
        # how to verify: the algorithm is ours to decide (invariant 6)
        if str(header.get("typ", "")).lower() not in ACCESS_TOKEN_TYPES:
            raise InvalidToken(f"typ {header.get('typ')!r} is not an access token")
        kid = header.get("kid")
        if not isinstance(kid, str):
            raise InvalidToken("no kid")
        key = await self.jwks.key(kid)
        if key is None:
            raise InvalidToken(f"unknown kid {kid!r}")

        try:
            # PINNED. With the token's own alg, "none" would skip the signature and "HS256" would
            # accept an HMAC keyed with our public key, which anyone can download.
            token_obj = jwt.decode(token, key, algorithms=["RS256"])
            if not isinstance(token_obj.claims, dict):
                raise InvalidToken("payload is not a JSON object")
            self.claims.validate(token_obj.claims)
        except JoseError as exc:
            raise InvalidToken(repr(exc))

        if not isinstance(token_obj.claims["scope"], str):
            raise InvalidToken("scope is not a string")
        return token_obj.claims


bearer = HTTPBearer(auto_error=False)


def _challenge(request: Request, **params: str) -> dict[str, str]:
    # RFC 6750 §3: tells the client which scheme, and why it failed
    attrs = ", ".join(f'{k}="{v}"' for k, v in {"realm": request.app.state.settings.audience, **params}.items())
    return {"WWW-Authenticate": f"Bearer {attrs}"}


async def access_token(
    request: Request, credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]
) -> dict[str, Any]:
    """The verified claims of the Bearer token, or 401."""

    if credentials is None:
        # RFC 6750 §3.1: no credentials at all gets a bare challenge, no error code
        raise HTTPException(401, "missing_token", headers=_challenge(request))

    try:
        return await request.app.state.verifier.verify(credentials.credentials)
    except InvalidToken as exc:
        # The reason goes to the logs, not to the caller: no hints for whoever forges tokens
        log.info("rejected token: %s", exc)
        raise HTTPException(401, "invalid_token", headers=_challenge(request, error="invalid_token"))
    except JwksUnavailable:
        # We can't tell valid from forged yet (issuer not reached): that's our failure, not the token's
        raise HTTPException(503, "jwks_unavailable", headers={"Retry-After": "5"})


def require_scope(scope: str):
    """Route dependency: a valid token that carries `scope`, else 401 / 403."""

    async def dependency(request: Request, claims: Annotated[dict[str, Any], Depends(access_token)]) -> dict[str, Any]:
        if scope not in claims["scope"].split():
            # 403, not 401: we know who you are, you are just not allowed here
            raise HTTPException(
                403, "insufficient_scope", headers=_challenge(request, error="insufficient_scope", scope=scope)
            )
        return claims

    return dependency
