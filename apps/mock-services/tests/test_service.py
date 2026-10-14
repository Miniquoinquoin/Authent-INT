"""The same image, configured as svc-impots or svc-cadastre: routes, scopes, health probes."""

import pytest
from httpx import ASGITransport, AsyncClient

from mockservices.config import Settings
from mockservices.main import create_app

from conftest import ISSUER


@pytest.fixture
async def service(jwks):
    """service("svc-impots") -> an AsyncClient on that instance. No lifespan: keys load lazily."""

    clients = []

    def build(audience: str) -> AsyncClient:
        app = create_app(Settings(service_name=audience, issuer=ISSUER, audience=audience), jwks=jwks)
        client = AsyncClient(transport=ASGITransport(app=app), base_url=f"https://{audience}.authentint.localhost")
        clients.append(client)
        return client

    yield build
    for client in clients:
        await client.aclose()


def bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# --- svc-impots ----------------------------------------------------------------------------

async def test_a_contribuable_reads_their_dossiers(service, issuer):
    response = await service("svc-impots").get("/dossiers", headers=bearer(issuer.token()))

    assert response.status_code == 200
    body = response.json()
    assert body["sub"] == "00000000-0000-0000-0000-00000000002a"
    assert len(body["dossiers"]) == 2


async def test_dossiers_are_deterministic_per_sub(service, issuer):
    impots = service("svc-impots")
    first = (await impots.get("/dossiers", headers=bearer(issuer.token()))).json()
    again = (await impots.get("/dossiers", headers=bearer(issuer.token()))).json()
    other = (await impots.get("/dossiers", headers=bearer(issuer.token(sub="00000000-0000-0000-0000-000000000001")))).json()

    assert first == again
    assert first["dossiers"] != other["dossiers"]


async def test_a_contribuable_cannot_create_a_dossier(service, issuer):
    response = await service("svc-impots").post(
        "/dossiers", json={"impot": "revenu", "annee": 2025}, headers=bearer(issuer.token())
    )

    assert response.status_code == 403


async def test_an_agent_creates_a_dossier(service, issuer):
    token = issuer.token(scope="svc:impots.read svc:impots.write svc:cadastre.read",
                         aud=["svc-cadastre", "svc-impots"])

    response = await service("svc-impots").post("/dossiers", json={"impot": "revenu", "annee": 2025},
                                                headers=bearer(token))

    assert response.status_code == 201
    assert response.json()["statut"] == "brouillon"


async def test_the_token_is_checked_before_the_body(service):
    # No 422 with field details for an anonymous caller
    response = await service("svc-impots").post("/dossiers", json={"nope": True})

    assert response.status_code == 401


# --- svc-cadastre --------------------------------------------------------------------------

async def test_an_agent_reads_the_parcelles(service, issuer):
    token = issuer.token(scope="svc:cadastre.read", aud=["svc-cadastre"])

    response = await service("svc-cadastre").get("/parcelles", headers=bearer(token))

    assert response.status_code == 200
    assert {p["id"] for p in response.json()["parcelles"]} == {"AB-0012", "AB-0013", "ZC-0101"}


async def test_nobody_edits_a_parcelle_without_cadastre_write(service, issuer):
    # Even an admin: svc:cadastre.write is granted to no role (ADR §18 q.12)
    admin = issuer.token(scope="svc:admin.users svc:admin.audit svc:cadastre.read svc:impots.read svc:impots.write",
                         aud=["svc-admin", "svc-cadastre", "svc-impots"])

    response = await service("svc-cadastre").patch("/parcelles/AB-0012", json={"nature": "bati"}, headers=bearer(admin))

    assert response.status_code == 403


async def test_a_token_with_cadastre_write_edits_a_parcelle(service, issuer):
    token = issuer.token(scope="svc:cadastre.write", aud=["svc-cadastre"])
    cadastre = service("svc-cadastre")

    response = await cadastre.patch("/parcelles/AB-0012", json={"nature": "bati"}, headers=bearer(token))
    missing = await cadastre.patch("/parcelles/XX-9999", json={"nature": "bati"}, headers=bearer(token))

    assert response.status_code == 200
    assert response.json()["nature"] == "bati"
    assert missing.status_code == 404


async def test_an_impots_token_is_rejected_by_svc_cadastre(service, issuer):
    response = await service("svc-cadastre").get("/parcelles", headers=bearer(issuer.token()))

    assert response.status_code == 401


# --- one image, two services ---------------------------------------------------------------

async def test_each_instance_serves_only_its_own_routes(service, issuer):
    assert (await service("svc-cadastre").get("/dossiers")).status_code == 404
    assert (await service("svc-impots").get("/parcelles")).status_code == 404


def test_an_unknown_audience_refuses_to_start(jwks):
    with pytest.raises(ValueError):
        create_app(Settings(service_name="svc-x", issuer=ISSUER, audience="svc-x"), jwks=jwks)


# --- startup and health --------------------------------------------------------------------

async def test_the_service_boots_while_the_issuer_is_down(jwks, issuer):
    # The auth-server may start after the mocks: boot must not crash, the first request retries
    issuer.down = True
    app = create_app(Settings(service_name="svc-impots", issuer=ISSUER, audience="svc-impots"), jwks=jwks)

    async with app.router.lifespan_context(app):
        assert not jwks.loaded


async def test_live_does_not_need_the_issuer(service, issuer):
    issuer.down = True

    assert (await service("svc-impots").get("/health/live")).status_code == 200


async def test_ready_waits_for_the_issuer_keys(service, issuer, clock):
    impots = service("svc-impots")
    issuer.down = True
    assert (await impots.get("/health/ready")).status_code == 503

    issuer.down = False
    clock.now += 2
    assert (await impots.get("/health/ready")).status_code == 200
