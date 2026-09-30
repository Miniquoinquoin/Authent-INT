"""domain/ is pure: these run without a database and pin the B0 contracts."""

from types import SimpleNamespace
from uuid import uuid4

import pytest

from pydantic import ValidationError

from authentint.domain.claims import AccessToken
from authentint.domain.claims import IdToken
from authentint.domain.errors import redirect_error
from authentint.domain.scopes import ALLOWED
from authentint.domain.scopes import audiences
from authentint.domain.scopes import grant
from authentint.infra.models.identity import Role


CLIENT = SimpleNamespace(allowed_scopes=["openid", "offline_access", "svc:impots.read", "svc:impots.write", "svc:admin.users"])


def test_openid_survives_the_intersection():
    assert "openid" in grant({"openid", "svc:impots.read"}, Role.contribuable, CLIENT)

def test_role_caps_the_scopes():
    assert grant({"openid", "svc:impots.write"}, Role.contribuable, CLIENT) == {"openid"}

def test_client_caps_the_scopes():
    assert grant({"svc:cadastre.read"}, Role.agent, CLIENT) == set()

def test_admin_scopes_never_reach_an_agent():
    assert grant({"svc:admin.users"}, Role.agent, CLIENT) == set()

def test_admin_has_every_agent_scope():
    assert ALLOWED[Role.agent] <= ALLOWED[Role.admin]  # architecture.md §9

def test_nobody_edits_the_cadastre_until_the_client_decides():
    # ADR §18 q.12: change this test together with ALLOWED once the client answers
    assert not any("svc:cadastre.write" in scopes for scopes in ALLOWED.values())

def test_one_audience_per_service():
    assert audiences({"openid", "svc:impots.read", "svc:impots.write", "svc:cadastre.read"}) == ["svc-cadastre", "svc-impots"]


def test_an_id_token_cannot_be_built_without_nonce():
    with pytest.raises(ValidationError):
        IdToken(iss="i", sub=uuid4(), aud="a", exp=1, iat=1, auth_time=1, acr="x", amr=["pwd"], sid=uuid4(),
                name="n", given_name="g", family_name="f", role=Role.agent)

def test_the_access_token_carries_no_role_nor_personal_data():
    # Resource Servers authorise on scope only (invariant 12); they never learn who the user is
    assert not {"role", "name", "email", "numero_fiscal"} & AccessToken.model_fields.keys()


def test_redirect_error_keeps_the_existing_query_and_the_state():
    r = redirect_error("https://app.test/cb?tenant=1", "invalid_request", "st4te")
    assert r.status_code == 302
    assert r.headers["location"] == "https://app.test/cb?tenant=1&error=invalid_request&state=st4te"
