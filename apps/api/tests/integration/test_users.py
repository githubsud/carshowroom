"""User management (BACKLOG 1.9): list, invite, change role, last-owner rule."""

import uuid
from typing import Any

import psycopg
from fastapi.testclient import TestClient

from tests.integration.conftest import NOUR, auth


def test_only_user_managers_list_users(client: TestClient) -> None:
    assert client.get("/api/v1/users", headers=auth("sales@nour.example", NOUR)).status_code == 403

    response = client.get("/api/v1/users", headers=auth("owner@nour.example", NOUR))
    assert response.status_code == 200
    emails = {m["email"] for m in response.json()}
    assert emails == {
        "owner@nour.example",
        "accountant@nour.example",
        "sales@nour.example",
        "partner@nour.example",
    }


def test_invite_existing_account_adds_membership(client: TestClient, admin_db: psycopg.Connection[Any]) -> None:
    # owner@doha.example already has an account (another showroom): no new account.
    response = client.post(
        "/api/v1/users/invite",
        headers=auth("owner@nour.example", NOUR),
        json={"email": "Owner@Doha.example", "role_code": "VIEWER"},
    )
    try:
        assert response.status_code == 201
        assert response.json()["role_code"] == "VIEWER"
        assert response.json()["email"] == "owner@doha.example"

        duplicate = client.post(
            "/api/v1/users/invite",
            headers=auth("owner@nour.example", NOUR),
            json={"email": "owner@doha.example", "role_code": "SALES"},
        )
        assert duplicate.status_code == 409
        assert duplicate.json()["error"]["code"] == "MEMBER_ALREADY_EXISTS"

        event = admin_db.execute(
            "select details ->> 'new_account' from public.audit_log "
            "where tenant_id = %s and action = 'USER_INVITED' order by id desc limit 1",
            (NOUR,),
        ).fetchone()
        assert event == ("false",)
    finally:
        admin_db.execute(
            "delete from public.memberships where tenant_id = %s and user_id = 'b0000000-0000-0000-0000-000000000001'",
            (NOUR,),
        )


def test_invite_new_email_creates_account(client: TestClient, admin_db: psycopg.Connection[Any]) -> None:
    email = f"new-{uuid.uuid4().hex[:8]}@nour.example"
    response = client.post(
        "/api/v1/users/invite",
        headers=auth("owner@nour.example", NOUR),
        json={"email": email, "full_name": "موظف جديد", "role_code": "SALES"},
    )
    try:
        assert response.status_code == 201, response.text
        assert response.json()["email"] == email
        assert response.json()["full_name"] == "موظف جديد"
    finally:
        admin_db.execute(
            "delete from public.memberships where user_id = (select id from auth.users where email = %s)",
            (email,),
        )
        admin_db.execute("delete from auth.users where email = %s", (email,))


def test_last_owner_cannot_be_demoted_or_disabled(client: TestClient) -> None:
    users = client.get("/api/v1/users", headers=auth("owner@nour.example", NOUR)).json()
    owner = next(m for m in users if m["role_code"] == "OWNER")
    for change in ({"role_code": "MANAGER"}, {"status": "DISABLED"}):
        response = client.patch(
            f"/api/v1/users/{owner['membership_id']}", headers=auth("owner@nour.example", NOUR), json=change
        )
        assert response.status_code == 409, change
        assert response.json()["error"]["code"] == "LAST_OWNER"


def test_role_change_is_applied_and_audited(client: TestClient, admin_db: psycopg.Connection[Any]) -> None:
    users = client.get("/api/v1/users", headers=auth("owner@nour.example", NOUR)).json()
    accountant = next(m for m in users if m["email"] == "accountant@nour.example")
    try:
        response = client.patch(
            f"/api/v1/users/{accountant['membership_id']}",
            headers=auth("owner@nour.example", NOUR),
            json={"role_code": "VIEWER"},
        )
        assert response.status_code == 200
        assert response.json()["role_code"] == "VIEWER"
        event = admin_db.execute(
            "select action from public.audit_log where entity_id = %s and action = 'MEMBERSHIP_CHANGED'",
            (accountant["membership_id"],),
        ).fetchone()
        assert event == ("MEMBERSHIP_CHANGED",)
    finally:
        admin_db.execute(
            "update public.memberships set role_id = (select id from public.roles where code = 'ACCOUNTANT' "
            "and tenant_id is null) where id = %s",
            (accountant["membership_id"],),
        )


def test_cannot_manage_users_of_another_tenant(client: TestClient, admin_db: psycopg.Connection[Any]) -> None:
    row = admin_db.execute(
        "select id::text from public.memberships where user_id = 'b0000000-0000-0000-0000-000000000001'"
    ).fetchone()
    assert row is not None
    response = client.patch(
        f"/api/v1/users/{row[0]}", headers=auth("owner@nour.example", NOUR), json={"status": "DISABLED"}
    )
    assert response.status_code == 404
    status = admin_db.execute("select status from public.memberships where id = %s", (row[0],)).fetchone()
    assert status == ("ACTIVE",)
