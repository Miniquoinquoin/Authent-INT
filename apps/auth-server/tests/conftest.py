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

from authentint.external.mailer import get_mailer
from authentint.infra.database import engine
from authentint.infra.database import get_session
from authentint.infra.models.identity import Role
from authentint.infra.models.identity import User
from authentint.infra.models.identity import UserStatus
from authentint.infra.models.oauth import ClientType
from authentint.infra.models.oauth import OAuthClients
from authentint.main import create_app
from authentint.security.passwords import hash_password


ALICE_PASSWORD = "correct-horse-battery"


@pytest.fixture
async def s():
    async with engine.connect() as conn:
        await conn.begin()
        # create_savepoint: a commit() in the code under test only releases a savepoint, the outer rollback still wins
        async with AsyncSession(bind=conn, join_transaction_mode="create_savepoint", expire_on_commit=False) as session:
            yield session
        await conn.rollback()

class Mailbox:
    """Stands in for the Mailer: keeps the e-mails instead of sending them."""

    def __init__(self):
        self.sent: list[dict] = []

    async def send(self, to: str, subject: str, body: str) -> None:
        self.sent.append({"to": to, "subject": subject, "body": body})

@pytest.fixture
def mailbox() -> Mailbox:
    return Mailbox()

@pytest.fixture
def make_client(s, mailbox):
    """A client seen by the server as coming from `ip` (one per simulated browser)."""

    def build(ip: str = "127.0.0.1") -> AsyncClient:
        app = create_app()
        app.dependency_overrides[get_session] = lambda: s  # the routes share the test's transaction
        app.dependency_overrides[get_mailer] = lambda: mailbox  # e-mails land in `mailbox.sent`
        return AsyncClient(transport=ASGITransport(app=app, client=(ip, 51000)), base_url="https://auth.authentint.local")

    return build

@pytest.fixture
async def client(make_client):
    async with make_client() as c:
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
def alice_password() -> str:
    return ALICE_PASSWORD

@pytest.fixture
async def alice(s) -> User:
    """An active contribuable whose password is ALICE_PASSWORD."""

    u = User(external_id="test-alice", numero_fiscal="1801234567890", email="alice@example.test",
             nom="Martin", prenom="Alice", password_hash=await hash_password(ALICE_PASSWORD),
             role=Role.contribuable, status=UserStatus.active)
    s.add(u)
    await s.flush()
    return u

@pytest.fixture
async def bob(s) -> User:
    """A contribuable imported from the directory, never activated: no password yet."""

    u = User(external_id="test-bob", numero_fiscal="1807654321098", email="bob@example.test",
             nom="Durand", prenom="Bob", password_hash=None,
             role=Role.contribuable, status=UserStatus.pending_activation)
    s.add(u)
    await s.flush()
    return u

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
