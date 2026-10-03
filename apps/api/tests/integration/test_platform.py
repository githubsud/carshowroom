"""Phase 9 acceptance: suspended tenants are read-only in the API and the
database; support access needs a live tenant grant; plan limits; signup;
the audit viewer and the data export; 2FA and HTTP hardening."""

import io
import json
import uuid
import zipfile
from collections.abc import Iterator
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Connection, text

from app.core.config import Settings
from app.core.errors import AppError
from app.domain.platform import SignupIn
from app.domain.vehicles import VehicleIn
from app.main import create_app
from app.services import platform, vehicles
from tests.integration.conftest import _ENV_FILE, DOHA, NOUR, auth

ADMIN = "admin@sayyara.example"


def _admin() -> dict[str, str]:
    return auth(ADMIN)


@pytest.fixture
def doha_suspended(client: TestClient) -> Iterator[None]:
    reason = {"reason": "اختبار الإيقاف"}
    response = client.patch(
        f"/api/v1/admin/tenants/{DOHA}", headers=_admin(), json={**reason, "subscription_status": "SUSPENDED"}
    )
    assert response.status_code == 200
    yield
    client.patch(f"/api/v1/admin/tenants/{DOHA}", headers=_admin(), json={**reason, "subscription_status": "TRIAL"})


def test_only_platform_admins_reach_the_console(client: TestClient) -> None:
    assert client.get("/api/v1/admin/tenants", headers=auth("owner@nour.example")).status_code == 403
    tenants = client.get("/api/v1/admin/tenants", headers=_admin()).json()
    nour = next(t for t in tenants if t["id"] == NOUR)
    assert nour["users"] >= 4
    assert nour["vehicles_in_stock"] > 0
    assert nour["plan_code"] == "TRIAL"


def test_a_suspended_tenant_is_read_only_in_the_api_and_the_database(
    client: TestClient, doha_suspended: None, admin_db: psycopg.Connection[Any]
) -> None:
    owner = auth("owner@doha.example", DOHA)
    assert client.get("/api/v1/customers", headers=owner).status_code == 200  # reading still works
    refused = client.post("/api/v1/customers", headers=owner, json={"name": "عميل"})
    assert refused.status_code == 423
    assert refused.json()["error"]["code"] == "TENANT_READ_ONLY"

    # Even a write that skips the API's check is refused by the database (SR040).
    admin_db.execute("set role app_api")
    admin_db.execute("select set_config('app.tenant_id', %s, false)", (DOHA,))
    with pytest.raises(psycopg.Error) as error:
        admin_db.execute("insert into public.customers (tenant_id, name) values (%s, 'x')", (DOHA,))
    assert error.value.sqlstate == "SR040"
    admin_db.execute("reset role")


def test_support_access_needs_a_live_grant(client: TestClient) -> None:
    owner = auth("owner@nour.example", NOUR)
    for grant in client.get("/api/v1/support-grants", headers=owner).json():
        if grant["active"]:
            client.post(f"/api/v1/support-grants/{grant['id']}/revoke", headers=owner)

    denied = client.get(f"/api/v1/admin/tenants/{NOUR}/support", headers=_admin())
    assert denied.status_code == 403
    assert denied.json()["error"]["code"] == "SUPPORT_NOT_GRANTED"

    grant = client.post("/api/v1/support-grants", headers=owner, json={"hours": 2, "reason": "مشكلة في التقرير"}).json()
    summary = client.get(f"/api/v1/admin/tenants/{NOUR}/support", headers=_admin())
    assert summary.status_code == 200
    assert summary.json()["counts"]["vehicles"] > 0

    audit = client.get("/api/v1/audit", headers=owner, params={"action": "SUPPORT_VIEW"}).json()
    assert audit["items"][0]["actor_kind"] == "PLATFORM"

    client.post(f"/api/v1/support-grants/{grant['id']}/revoke", headers=owner)
    assert client.get(f"/api/v1/admin/tenants/{NOUR}/support", headers=_admin()).status_code == 403
    too_long = client.post("/api/v1/support-grants", headers=owner, json={"hours": 100, "reason": "طويل"})
    assert too_long.status_code == 422


def test_plan_limits_refuse_more_stock(fresh_tenant: tuple[Connection, uuid.UUID]) -> None:
    conn, _ = fresh_tenant
    conn.execute(text("reset role"))
    conn.execute(
        text("update public.plans set limits = jsonb_set(limits, '{vehicles_in_stock}', '1') where code = 'TRIAL'")
    )
    conn.execute(text("set local role app_api"))
    vehicles.create_vehicle(conn, VehicleIn(make="Kia", model="Rio"))
    with pytest.raises(AppError) as limit:
        vehicles.create_vehicle(conn, VehicleIn(make="Kia", model="Picanto"))
    assert (limit.value.code, limit.value.details["max"]) == ("PLAN_LIMIT_REACHED", 1)
    # A trade-in taken in a sale is not refused (D-114).
    vehicles.create_vehicle(conn, VehicleIn(make="Kia", model="Ceed"), count_against_plan=False)


def test_signup_creates_a_trial_showroom_owned_by_the_user(fresh_tenant: tuple[Connection, uuid.UUID]) -> None:
    conn, _ = fresh_tenant
    user = uuid.UUID("a0000000-0000-0000-0000-000000000004")  # partner@nour owns no showroom
    tenant_id = platform.signup(conn, SignupIn(name_ar="معرض جديد", country_code="QA"), user_id=user)
    conn.execute(text("reset role"))
    row = conn.execute(
        text(
            "select t.currency_code, s.status, r.code from public.tenants t "
            "join public.subscriptions s on s.tenant_id = t.id "
            "join public.memberships m on m.tenant_id = t.id join public.roles r on r.id = m.role_id where t.id = :t"
        ),
        {"t": tenant_id},
    ).one()
    assert tuple(row) == ("QAR", "TRIAL", "OWNER")


def test_owner_exports_everything(client: TestClient) -> None:
    response = client.get("/api/v1/tenant/export", headers=auth("owner@nour.example", NOUR))
    assert response.status_code == 200
    archive = zipfile.ZipFile(io.BytesIO(response.content))
    manifest = json.loads(archive.read("manifest.json"))
    assert manifest["tables"]["vehicles"] > 0
    assert manifest["tables"]["journal_lines"] > 0
    assert all(row["tenant_id"] == NOUR for row in json.loads(archive.read("vehicles.json")))
    assert client.get("/api/v1/tenant/export", headers=auth("sales@nour.example", NOUR)).status_code == 403


def test_audit_viewer_shows_before_and_after(client: TestClient) -> None:
    owner = auth("owner@nour.example", NOUR)
    created = client.post("/api/v1/customers", headers=owner, json={"name": "عميل للتدقيق"}).json()
    client.patch(f"/api/v1/customers/{created['id']}", headers=owner, json={"name": "عميل للتدقيق ٢"})
    page = client.get("/api/v1/audit", headers=owner, params={"entity_type": "customers"}).json()
    update = next(i for i in page["items"] if i["entity_id"] == created["id"] and i["before"])
    assert update["before"]["name"] == "عميل للتدقيق"
    assert update["after"]["name"] == "عميل للتدقيق ٢"
    assert client.get("/api/v1/audit", headers=auth("sales@nour.example", NOUR)).status_code == 403


def test_two_step_sign_in_is_required_once_enrolled(client: TestClient, admin_db: psycopg.Connection[Any]) -> None:
    accountant = "a0000000-0000-0000-0000-000000000002"
    factor = uuid.uuid4()
    admin_db.execute(
        "insert into auth.mfa_factors "
        "(id, user_id, friendly_name, factor_type, status, created_at, updated_at, secret) "
        "values (%s, %s, 'test', 'totp', 'verified', now(), now(), 'X')",
        (factor, accountant),
    )
    try:
        refused = client.get("/api/v1/tenant", headers=auth("accountant@nour.example", NOUR))
        assert refused.status_code == 401
        assert refused.json()["error"]["code"] == "MFA_REQUIRED"
    finally:
        admin_db.execute("delete from auth.mfa_factors where id = %s", (factor,))
    assert client.get("/api/v1/tenant", headers=auth("accountant@nour.example", NOUR)).status_code == 200


def test_rate_limits_and_security_headers() -> None:
    settings = Settings(_env_file=_ENV_FILE, environment="testing", rate_limits_enabled=True)  # type: ignore[call-arg]
    with TestClient(create_app(settings)) as guarded:
        health = guarded.get("/healthz")
        assert health.headers["X-Content-Type-Options"] == "nosniff"
        assert health.headers["X-Frame-Options"] == "DENY"
        statuses = [guarded.post("/api/v1/signup", json={}).status_code for _ in range(6)]
        assert statuses[:5] == [401] * 5
        assert statuses[5] == 429
        big = guarded.post("/api/v1/imports", content=b"x", headers={"Content-Length": str(20 * 1024 * 1024)})
        assert big.status_code == 413


def test_the_export_handles_every_column_type() -> None:
    # The audit log keeps the visitor's IP (inet): the export once failed on it.
    from ipaddress import IPv4Address
    from uuid import UUID

    from app.services.platform import _jsonable

    assert _jsonable(IPv4Address("41.33.10.5")) == "41.33.10.5"
    assert _jsonable(UUID("11111111-1111-1111-1111-111111111111")) == "11111111-1111-1111-1111-111111111111"
