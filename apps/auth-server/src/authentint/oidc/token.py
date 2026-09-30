from pydantic import BaseModel
from pydantic import Field
from typing import Literal
from urllib.parse import unquote
from joserfc.jwk import RSAKey
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi.security import HTTPBasicCredentials

from authentint.config import settings
from authentint.infra.models.oauth import OAuthClients
from authentint.infra.models.oauth import ClientType
from authentint.domain.errors import OAuthError
from authentint.clients import queries as clients
from authentint.security.passwords import verify_password


class TokenBody(BaseModel):
    grant_type: Literal["authorization_code"]
    code: str
    redirect_uri: str
    client_id: str
    code_verifier: str = Field(min_length=43, max_length=128)


async def authenticate_client(session: AsyncSession, client_id: str, credentials: HTTPBasicCredentials | None) -> OAuthClients:
    # RFC 6749 §2.3.1: Basic id/secret are URL-encoded; must match the body's client_id
    if credentials is not None and unquote(credentials.username) != client_id:
        raise OAuthError("invalid_client")

    client = await clients.get(session, client_id)
    if client is None:
        raise OAuthError("invalid_client")

    # public clients have no secret; PKCE in consume_code is their proof
    if client.type == ClientType.public and credentials is not None:
        raise OAuthError("invalid_client")

    if client.type == ClientType.confidential and (
        credentials is None
        or not client.secret_hash
        or not await verify_password(client.secret_hash, unquote(credentials.password))
    ):
        raise OAuthError("invalid_client")

    if "authorization_code" not in client.allowed_grants:
        raise OAuthError("unauthorized_client")

    return client

def sign(claims: dict, key: RSAKey) -> str:
    pass

async def access_claims(row, now) -> dict:
    pass

async def issue_refresh(session: AsyncSession, row) -> str:
    pass
