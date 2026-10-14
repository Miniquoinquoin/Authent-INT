"""
Signing keys lifecycle: next -> active -> retired, and the JWKS that publishes them.
JWTs themselves are signed in oidc/token.py with active().
"""


import secrets

from functools import lru_cache

from cryptography.fernet import Fernet
from joserfc.jwk import RSAKey
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from sqlalchemy import select
from sqlalchemy import func
from datetime import datetime
from datetime import UTC
from datetime import timedelta

from authentint.config import settings
from authentint.infra.models.keys import SigningKeys
from authentint.infra.models.keys import KeyStatus


fernet = Fernet(settings.key_encryption_key)
# A key that signs (active) or will sign (next) stays published: no expiry until rotate() retires it
FAR_FUTURE = datetime(9999, 1, 1, tzinfo=UTC)


def _new_kid() -> str:
    return secrets.token_urlsafe(16)

def _new_key(status: KeyStatus) -> SigningKeys:
    """
    """

    kid = _new_kid()
    key = RSAKey.generate_key(2048, parameters={"kid": kid, "use": "sig", "alg": "RS256"})
    # Private RSA signing keys are stored in Postgres
    # To prevent people from forging valid ID or accessing token for any user (/admin) Fernet is used to ecrypt the key
    private_pem = key.as_pem(private=True)
    encrypted_pem = fernet.encrypt(private_pem)

    return SigningKeys(
        kid=kid, alg="RS256", status=status,
        public_jwk=key.as_dict(private=False),
        private_pem_encrypted=encrypted_pem.decode(),
        not_before=datetime.now(UTC), not_after=FAR_FUTURE
    )

async def ensure_active_key(session: AsyncSession) -> None:
    await session.execute(text("SELECT pg_advisory_xact_lock(1)"))
    if await session.scalar(select(SigningKeys).where(SigningKeys.status == KeyStatus.active)) is None:
        session.add(_new_key(KeyStatus.active))
        session.add(_new_key(KeyStatus.next))
    await session.commit()

async def rotate(session: AsyncSession) -> None:
    await session.execute(text("SELECT pg_advisory_xact_lock(1)"))
    old = await session.scalar(select(SigningKeys).where(SigningKeys.status == KeyStatus.active))
    new = await session.scalar(select(SigningKeys).where(SigningKeys.status == KeyStatus.next))
    old.status = KeyStatus.retired
    old.not_after = datetime.now(UTC) + timedelta(seconds=max(settings.access_token_ttl, settings.id_token_ttl))
    new.status = KeyStatus.active
    session.add(_new_key(KeyStatus.next))

async def jwks(session: AsyncSession) -> dict:
    rows = await session.scalars(select(SigningKeys).where(SigningKeys.not_after > func.now()))

    return {"keys": [row.public_jwk for row in rows]}

@lru_cache(maxsize=8)
def _private_key(kid: str, private_pem_encrypted: str) -> RSAKey:
    """
    Decrypt + PEM import once per key, not once per token: cryptography validates the RSA key on
    import (on the event loop), which kept one replica from serving 30 /token per second
    (docs/load-report.md). A kid never changes its key material, so the cache cannot go stale;
    a rotation only adds a new kid.
    """

    pem = fernet.decrypt(private_pem_encrypted.encode())

    return RSAKey.import_key(pem, parameters={"kid": kid})

async def active(session: AsyncSession) -> RSAKey:
    row = await session.scalar(select(SigningKeys).where(SigningKeys.status == KeyStatus.active))

    return _private_key(row.kid, row.private_pem_encrypted)
