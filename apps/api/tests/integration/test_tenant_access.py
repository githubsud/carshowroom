"""Phase 1 acceptance through the API: users see only their tenant, permissions
are enforced, suspended tenants are read-only, and changes are audited."""

from typing import Any

import psycopg
from fastapi.testclient import TestClient

from app.domain.permissions import Permission
from tests.integration.conftest import DOHA, NOUR, auth


def test_me_lists_only_the_users_tenants(client: TestClient) -> None:
    response = client.get("/api/v1/me", headers=auth("owner@nour.example"))
    assert response.status_code == 200
    body = response.json()
    assert body["user"]["email"] == "owner@nour.example"
    assert [m["tenant_id"] for m in body["memberships"]] == [NOUR]
    membership = body["memberships"][0]
    assert membership["role_code"] == "OWNER"
    assert Permission.TENANT_SETTINGS_MANAGE in membership["permissions"]
    assert membership["feature_flags"]["installments"] is True


def test_partner_in_two_showrooms_sees_both(client: TestClient) -> None:
    body = client.get("/api/v1/me", headers=auth("partner@nour.example")).json()
    assert {m["tenant_id"] for m in body["memberships"]} == {NOUR, DOHA}
    assert all(m["permissions"] == ["partner.view_own"] for m in body["memberships"])


def test_sales_permissions_never_include_cost(client: TestClient) -> None:
    body = client.get("/api/v1/me", headers=auth("sales@nour.example")).json()
    permissions = body["memberships"][0]["permissions"]
    assert Permission.VEHICLE_VIEW in permissions
    assert Permission.VEHICLE_VIEW_COST not in permissions
    assert Permission.VEHICLE_VIEW_MIN_PRICE not in permissions


def test_member_reads_own_tenant(client: TestClient) -> None:
    response = client.get("/api/v1/tenant", headers=auth("sales@nour.example", NOUR))
    assert response.status_code == 200
    body = response.json()
    assert body["profile"]["name_ar"] == "معرض النور للسيارات"
    assert body["settings"]["sale_cancellation_method"] == "REFUND_LIABILITY"  # D-41 default
    assert body["settings"]["profit_policy"] == "PERIODIC"  # D-40 default


def test_other_tenant_is_denied(client: TestClient) -> None:
    for method, path in (("GET", "/api/v1/tenant"), ("PATCH", "/api/v1/tenant/settings")):
        response = client.request(method, path, headers=auth("owner@nour.example", DOHA), json={})
        assert response.status_code == 403, path
        assert response.json()["error"]["code"] == "TENANT_ACCESS_DENIED"


def test_unknown_tenant_looks_the_same_as_a_foreign_one(client: TestClient) -> None:
    response = client.get("/api/v1/tenant", headers=auth("owner@nour.example", "99999999-9999-9999-9999-999999999999"))
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "TENANT_ACCESS_DENIED"


def test_settings_require_permission(client: TestClient) -> None:
    for email in ("sales@nour.example", "accountant@nour.example"):
        response = client.patch(
            "/api/v1/tenant/settings", headers=auth(email, NOUR), json={"digit_style": "ARABIC_INDIC"}
        )
        assert response.status_code == 403, email
        error = response.json()["error"]
        assert error["code"] == "PERMISSION_DENIED"
        assert error["details"]["permission"] == "tenant.settings.manage"


def test_owner_updates_settings_and_it_is_audited(client: TestClient, admin_db: psycopg.Connection[Any]) -> None:
    response = client.patch(
        "/api/v1/tenant/settings",
        headers={**auth("owner@nour.example", NOUR), "X-Request-Id": "it-settings-1"},
        json={"digit_style": "ARABIC_INDIC", "aging_thresholds": [20, 45, 75]},
    )
    try:
        assert response.status_code == 200
        assert response.json()["settings"]["digit_style"] == "ARABIC_INDIC"
        assert response.json()["settings"]["aging_thresholds"] == [20, 45, 75]

        row = admin_db.execute(
            """
            select actor_user_id::text, before ->> 'digit_style', after ->> 'digit_style'
              from public.audit_log
             where tenant_id = %s and entity_type = 'tenant_settings' and request_id = 'it-settings-1'
            """,
            (NOUR,),
        ).fetchone()
        assert row == ("a0000000-0000-0000-0000-000000000001", "WESTERN", "ARABIC_INDIC")
    finally:
        admin_db.execute(
            "update public.tenant_settings set digit_style = 'WESTERN', aging_thresholds = '{30,60,90}' "
            "where tenant_id = %s",
            (NOUR,),
        )


def test_invalid_settings_are_rejected(client: TestClient) -> None:
    response = client.patch(
        "/api/v1/tenant/settings",
        headers=auth("owner@nour.example", NOUR),
        json={"aging_thresholds": [60, 30, 90]},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_suspended_tenant_is_read_only(client: TestClient, admin_db: psycopg.Connection[Any]) -> None:
    admin_db.execute("update public.subscriptions set status = 'SUSPENDED' where tenant_id = %s", (NOUR,))
    try:
        assert client.get("/api/v1/tenant", headers=auth("owner@nour.example", NOUR)).status_code == 200
        response = client.patch(
            "/api/v1/tenant/profile", headers=auth("owner@nour.example", NOUR), json={"address": "x"}
        )
        assert response.status_code == 423
        assert response.json()["error"]["code"] == "TENANT_READ_ONLY"
    finally:
        admin_db.execute("update public.subscriptions set status = 'TRIAL' where tenant_id = %s", (NOUR,))


def test_disabled_membership_loses_access(client: TestClient, admin_db: psycopg.Connection[Any]) -> None:
    user = "a0000000-0000-0000-0000-000000000003"
    admin_db.execute("update public.memberships set status = 'DISABLED' where user_id = %s", (user,))
    try:
        response = client.get("/api/v1/tenant", headers=auth("sales@nour.example", NOUR))
        assert response.status_code == 403
    finally:
        admin_db.execute("update public.memberships set status = 'ACTIVE' where user_id = %s", (user,))


def test_permission_catalogue_matches_database(admin_db: psycopg.Connection[Any]) -> None:
    in_db = {row[0] for row in admin_db.execute("select code from public.permissions")}
    assert in_db == {p.value for p in Permission}
