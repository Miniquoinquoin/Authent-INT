"""
/me/audit (one's own history) and /admin/audit (filters, id cursor, CSV export). A user never
sees another user's events; the export carries no secret and no numero fiscal (audit.emit refuses
them, the CSV is the same rows); the audit API needs svc:admin.audit, svc:admin.users is not enough.
"""

import csv
import io

from authentint.audit import audit
from authentint.audit.middleware import request_id_var
from authentint.audit.routes import CSV_COLUMNS
from authentint.infra.models.identity import Role


def bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}

async def events(s, user, n: int, event_type: str = "test.event", **kw):
    for _ in range(n):
        await audit.emit(s, event_type, actor=user.id if user else None, outcome="success", detail={}, **kw)
    await s.flush()


async def test_my_audit_is_mine_only_newest_first(client, s, alice, make_user, access_token):
    await events(s, alice, 3)
    await events(s, await make_user(), 2)

    r = await client.get("/me/audit", headers=bearer(await access_token(alice, "openid")))

    assert r.status_code == 200
    items = r.json()["items"]
    assert len(items) == 3 and all(i["actor_user_id"] == str(alice.id) for i in items)
    assert [i["id"] for i in items] == sorted((i["id"] for i in items), reverse=True)
    assert r.json()["next_before"] is None

async def test_my_audit_pages_with_the_id_cursor(client, s, alice, access_token):
    await events(s, alice, 5)
    token = await access_token(alice, "openid")

    first = (await client.get("/me/audit", params={"limit": 2}, headers=bearer(token))).json()
    second = (await client.get("/me/audit", params={"limit": 2, "before": first["next_before"]}, headers=bearer(token))).json()
    last = (await client.get("/me/audit", params={"limit": 2, "before": second["next_before"]}, headers=bearer(token))).json()

    ids = [i["id"] for page in (first, second, last) for i in page["items"]]
    assert len(ids) == 5 and len(set(ids)) == 5 and ids == sorted(ids, reverse=True)
    assert first["next_before"] == first["items"][-1]["id"]
    assert last["next_before"] is None

async def test_my_audit_bounds_the_limit(client, alice, access_token):
    token = await access_token(alice, "openid")
    assert (await client.get("/me/audit", params={"limit": 0}, headers=bearer(token))).status_code == 422
    assert (await client.get("/me/audit", params={"limit": 101}, headers=bearer(token))).status_code == 422

async def test_my_audit_needs_an_idp_token(client, alice, access_token):
    assert (await client.get("/me/audit")).status_code == 401
    assert (await client.get("/me/audit", headers=bearer(await access_token(alice, "svc:impots.read")))).status_code == 401


async def test_admin_audit_filters(client, s, alice, make_user, access_token):
    admin = await make_user(Role.admin)
    await events(s, alice, 2, "test.filter_a", client_id="test-spa")
    await events(s, alice, 1, "test.filter_b")
    token = await access_token(admin, "openid svc:admin.audit")

    r = await client.get("/admin/audit", params={"event_type": "test.filter_a", "actor_user_id": str(alice.id), "client_id": "test-spa",
                                                  "outcome": "success"}, headers=bearer(token))

    assert r.status_code == 200
    assert [i["event_type"] for i in r.json()["items"]] == ["test.filter_a", "test.filter_a"]

async def test_admin_audit_time_window(client, s, alice, make_user, access_token):
    admin = await make_user(Role.admin)
    await events(s, alice, 1, "test.window")
    token = await access_token(admin, "openid svc:admin.audit")

    r = await client.get("/admin/audit", params={"event_type": "test.window", "until": "2000-01-01T00:00:00Z"}, headers=bearer(token))
    assert r.json()["items"] == []
    r = await client.get("/admin/audit", params={"event_type": "test.window", "since": "2000-01-01T00:00:00Z"}, headers=bearer(token))
    assert len(r.json()["items"]) == 1

async def test_admin_audit_csv_export(client, s, alice, make_user, access_token):
    admin = await make_user(Role.admin)
    await events(s, alice, 3, "test.csv")
    await audit.emit(s, "test.csv", actor=None, outcome="failure", detail={})
    await s.flush()

    r = await client.get("/admin/audit", params={"event_type": "test.csv", "format": "csv"},
                         headers=bearer(await access_token(admin, "openid svc:admin.audit")))

    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")
    assert r.headers["content-disposition"] == 'attachment; filename="audit.csv"'
    rows = list(csv.reader(io.StringIO(r.text)))
    assert rows[0] == CSV_COLUMNS and len(rows) == 5
    assert alice.numero_fiscal not in r.text and alice.numero_fiscal_hmac not in r.text

async def test_csv_cells_never_start_a_formula(client, s, alice, make_user, access_token):
    # request_id comes from the X-Request-Id header: attacker-chosen, and a spreadsheet would run it
    admin = await make_user(Role.admin)
    reset = request_id_var.set("=HYPERLINK(\"https://evil.test\")")
    await events(s, alice, 1, "test.formula")
    request_id_var.reset(reset)

    r = await client.get("/admin/audit", params={"event_type": "test.formula", "format": "csv"},
                         headers=bearer(await access_token(admin, "openid svc:admin.audit")))

    [row] = list(csv.DictReader(io.StringIO(r.text)))
    assert row["request_id"].startswith("'=")

async def test_admin_audit_needs_the_audit_scope(client, make_user, access_token):
    admin = await make_user(Role.admin)
    assert (await client.get("/admin/audit")).status_code == 401
    r = await client.get("/admin/audit", headers=bearer(await access_token(admin, "openid svc:admin.users")))
    assert r.status_code == 403 and r.headers["www-authenticate"] == 'Bearer error="insufficient_scope"'
