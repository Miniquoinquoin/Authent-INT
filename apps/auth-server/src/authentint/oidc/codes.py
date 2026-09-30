from __future__ import annotations

import secrets
import hashlib
import base64

from datetime import datetime
from datetime import timedelta
from datetime import timezone
from typing import TYPE_CHECKING
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import update
from sqlalchemy import select
from sqlalchemy import func

from authentint.config import settings
from authentint.infra.models.audit import Sessions
from authentint.infra.models.oauth import OAuthAuthorizationCodes
from authentint.infra.models.oauth import OAuthRefreshTokens
from authentint.security.passwords import hash_token
from authentint.domain.errors import OAuthError

if TYPE_CHECKING:
    from authentint.oidc.authorize import AuthorizeParams  # hint only: a runtime import would be circular otherwise


async def issue_code(session: AsyncSession, params: AuthorizeParams, sso: Sessions) -> str:
    token = secrets.token_urlsafe(32)
    oauth_auth_code = OAuthAuthorizationCodes(
        code_hash= hash_token(token),
        client_id=params.client_id,
        user_id=sso.user_id,
        session_id=sso.id,
        redirect_uri=params.redirect_uri,
        scope=params.scope,
        nonce=params.nonce,
        code_challenge=params.code_challenge,
        code_challenge_method=params.code_challenge_method,
        auth_time=sso.created_at,
        acr=sso.acr,
        amr=sso.amr,
        expires_at=datetime.now(timezone.utc) + timedelta(seconds=settings.code_ttl)
    )

    session.add(oauth_auth_code)
    await session.commit()

    # Returns the token in plain text: TLS is the protection
    return token

async def consume_code(session: AsyncSession, code: str, client_id: str, redirect_uri: str, code_verifier: str) -> OAuthAuthorizationCodes:
    h_code = hash_token(code)
    statement = update(OAuthAuthorizationCodes).where(OAuthAuthorizationCodes.code_hash == h_code, OAuthAuthorizationCodes.consumed_at.is_(None), OAuthAuthorizationCodes.expires_at > func.now()).values(consumed_at=func.now()).returning(OAuthAuthorizationCodes)
    row: OAuthAuthorizationCodes | None = await session.scalar(statement)

    await session.commit()

    if row is None:
        # The code can have three states: doesn't exist, expired, already used
        # The last case means the code leaked and server has to defend by updating the tables

        row = await session.scalar(select(OAuthAuthorizationCodes).where(OAuthAuthorizationCodes.code_hash == h_code))

        if row is not None:
            if row.consumed_at is not None:
                # An already existing code is being used --> revoking the refresh token linked to it to protect the server
                statement = update(OAuthRefreshTokens).where(OAuthRefreshTokens.session_id == row.session_id, OAuthRefreshTokens.client_id == row.client_id, OAuthRefreshTokens.revoked_at.is_(None)).values(revoked_at=func.now(), revocation_reason="code_replay")
                await session.execute(statement)
                await session.commit()

        # Raising "invalid_grant" in every case
        raise(OAuthError("invalid_grant"))

    if row.client_id != client_id or row.redirect_uri != redirect_uri:
        raise(OAuthError("invalid_grant"))

    # Checking PKCE (copy pasted)
    # PKCE S256 (RFC 7636 §4.6): BASE64URL(SHA256(verifier)) without "=" padding
    digest = hashlib.sha256(code_verifier.encode()).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()

    # At /authorise, the client made up a random code_verifier and kept it while seding the code_challenge (S256)
    # At /token, the client sends the verifier that is hashed the same way as in the previous process to check if it matches in the future
    if not secrets.compare_digest(challenge, row.code_challenge):
        raise OAuthError("invalid_grant")

    return row
