"""
/metrics (ops/metrics.py, ADR §9 Ops). The registry is global to the process: tests compare
before/after values, never absolute ones. That Caddy hides /metrics from the internet is
checked live (docs/load-report.md), not here: the ASGI client never goes through Caddy.
"""

from prometheus_client import REGISTRY


def value(name: str, **labels) -> float:
    return REGISTRY.get_sample_value(name, labels) or 0.0


async def test_metrics_is_prometheus_text_with_our_series(client):
    await client.get("/health/live")

    r = await client.get("/metrics")

    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/plain")
    for name in ("authentint_http_requests_total", "authentint_http_request_duration_seconds_bucket",
                 "authentint_logins_total", "authentint_token_grants_total"):
        assert name in r.text

async def test_a_request_is_counted_under_its_route_template_never_its_raw_path(client, make_user, access_token):
    user = await make_user()
    token = await access_token(user, "openid")
    labels = {"method": "DELETE", "route": "/me/sessions/{session_id}", "status": "404"}
    before = value("authentint_http_requests_total", **labels)

    r = await client.delete("/me/sessions/00000000-0000-0000-0000-000000000000", headers={"Authorization": f"Bearer {token}"})

    assert r.status_code == 404
    assert value("authentint_http_requests_total", **labels) == before + 1
    assert "00000000-0000-0000-0000-000000000000" not in (await client.get("/metrics")).text  # no id ever becomes a label

async def test_an_unknown_path_is_one_fixed_label(client):
    before = value("authentint_http_requests_total", method="GET", route="unmatched", status="404")
    await client.get("/does-not-exist/123")
    assert value("authentint_http_requests_total", method="GET", route="unmatched", status="404") == before + 1

async def test_login_outcomes_are_counted(client, authorize_params, alice, alice_password):
    r = await client.get("/authorize", params=authorize_params())
    uid = r.headers["location"].split("uid=")[1]
    failures, successes = value("authentint_logins_total", outcome="failure"), value("authentint_logins_total", outcome="success")

    await client.post(f"/interaction/{uid}/login", json={"numero_fiscal": alice.numero_fiscal, "password": "wrong"})
    await client.post(f"/interaction/{uid}/login", json={"numero_fiscal": alice.numero_fiscal, "password": alice_password})

    assert value("authentint_logins_total", outcome="failure") == failures + 1
    assert value("authentint_logins_total", outcome="success") == successes + 1

async def test_a_failed_grant_is_counted_as_a_failure(client):
    before = value("authentint_token_grants_total", grant_type="authorization_code", outcome="failure")
    r = await client.post("/token", data={"grant_type": "authorization_code", "code": "guess", "redirect_uri": "https://app.test/cb",
                                          "client_id": "nobody", "code_verifier": "v" * 43})
    assert r.status_code == 400
    assert value("authentint_token_grants_total", grant_type="authorization_code", outcome="failure") == before + 1
