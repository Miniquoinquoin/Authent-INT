"""
scripts/bootstrap.py: what a non-dev deployment runs to get its client and its directory users.
A rerun must never undo what happened since: an activation, a lock, a client edited by an admin.
"""

from pathlib import Path

from sqlalchemy import select

import scripts.bootstrap as bootstrap
from authentint.config import settings
from authentint.external.directory import DirectoryUser
from authentint.external.directory import JsonDirectory
from authentint.external.directory import role_for
from authentint.infra.models.identity import Role
from authentint.infra.models.identity import User
from authentint.infra.models.identity import UserStatus
from authentint.infra.models.oauth import OAuthClients
from authentint.security.identifiers import numero_fiscal_digest


class OneUser:
    def __init__(self, email: str = "new@test.example"):
        self.user = DirectoryUser(external_id="test-bootstrap", numero_fiscal="1809999999999", nom="Nouveau", prenom="Compte",
                                  email=email, groups=["cn=agents,ou=groupes,dc=dgfip,dc=local"])

    def list_all(self):
        return iter([self.user])


async def imported(s) -> User:
    return await s.scalar(select(User).where(User.external_id == "test-bootstrap").execution_options(populate_existing=True))


async def test_a_new_user_waits_for_activation(s):
    assert await bootstrap.import_users(s, OneUser()) == 1

    user = await imported(s)
    assert user.status == UserStatus.pending_activation
    assert user.password_hash is None
    assert user.role == Role.agent
    assert user.numero_fiscal_hmac == numero_fiscal_digest("1809999999999")
    assert user.synced_at is not None


async def test_a_rerun_refreshes_identity_but_never_status_or_password(s):
    await bootstrap.import_users(s, OneUser())
    user = await imported(s)
    user.status, user.password_hash = UserStatus.active, "$argon2id$kept"
    await s.flush()

    await bootstrap.import_users(s, OneUser(email="changed@test.example"))

    user = await imported(s)
    assert user.email == "changed@test.example"
    assert user.status == UserStatus.active
    assert user.password_hash == "$argon2id$kept"


async def test_the_client_uses_this_deployments_origin(monkeypatch):
    monkeypatch.setattr(settings, "public_base_url", "https://app.client.example")

    values = bootstrap.portail_client()

    assert values["redirect_uris"] == ["https://app.client.example/callback"]
    assert values["post_logout_redirect_uris"] == ["https://app.client.example/"]


async def test_a_rerun_keeps_a_client_edited_by_an_admin(s):
    await bootstrap.register_client(s)
    client = await s.get(OAuthClients, "portail-web")
    client.redirect_uris = ["https://edited.example/callback"]
    await s.flush()

    await bootstrap.register_client(s)

    await s.refresh(client)
    assert client.redirect_uris == ["https://edited.example/callback"]


def test_the_example_file_has_one_user_per_role():
    path = Path(bootstrap.__file__).with_name("example_users.json")
    users = list(JsonDirectory(str(path)).list_all())

    assert sorted(role_for(u.groups).value for u in users) == ["admin", "agent", "contribuable"]
    assert all(u.external_id.startswith("example-") for u in users)
