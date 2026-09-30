"""
Shared fixtures. Tests run INSIDE the container (`make test`), against the compose Postgres:
no SQLite, which would accept what Postgres refuses.

Every test gets one transaction that is rolled back at the end, so tests never see each
other's rows and the dev database is left untouched.
"""

import pytest

from httpx import ASGITransport
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from authentint.infra.database import engine
from authentint.infra.database import get_session
from authentint.infra.models.oauth import ClientType
from authentint.infra.models.oauth import OAuthClients
from authentint.main import create_app


@pytest.fixture
async def s():
    async with engine.connect() as conn:
        await conn.begin()
        # create_savepoint: a commit() in the code under test only releases a savepoint, the outer rollback still wins
        async with AsyncSession(bind=conn, join_transaction_mode="create_savepoint", expire_on_commit=False) as session:
            yield session
        await conn.rollback()

@pytest.fixture
async def client(s):
    app = create_app()
    app.dependency_overrides[get_session] = lambda: s  # the routes share the test's transaction
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://auth.authentint.local") as c:
        yield c

@pytest.fixture
async def spa(s) -> OAuthClients:
    c = OAuthClients(id="test-spa", name="Test SPA", type=ClientType.public, secret_hash=None,
                     redirect_uris=["https://app.test/cb"], post_logout_redirect_uris=[],
                     allowed_grants=["authorization_code"], allowed_scopes=["openid", "svc:impots.read"],
                     require_consent=False)
    s.add(c)
    await s.flush()
    return c

@pytest.fixture
def authorize_params(spa):
    """A valid /authorize query for `spa`; override any parameter by keyword (None removes it)."""

    def build(**overrides) -> dict:
        params = {"response_type": "code", "client_id": spa.id, "redirect_uri": spa.redirect_uris[0],
                  "scope": "openid svc:impots.read", "state": "st4te", "nonce": "n0nce",
                  "code_challenge": "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM", "code_challenge_method": "S256"}
        params.update(overrides)
        return {k: v for k, v in params.items() if v is not None}

    return build
