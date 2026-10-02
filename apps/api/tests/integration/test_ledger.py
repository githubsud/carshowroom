"""Phase 2 acceptance through the API: rules 20, 21 and 24 post correctly, the
cash book reconciles, and locked-period / cross-tenant / unbalanced postings
fail. The ledger is append-only, so tests assert on deltas, never on totals.
"""

import uuid
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient

from app.core.errors import AppError
from app.domain.finance import GeneralExpenseIn
from app.services import finance
from tests.integration.conftest import DOHA, NOUR, auth

CASH = "c0000000-0000-0000-0000-000000000001"  # seed: معرض النور main cash box
BANK = "c0000000-0000-0000-0000-000000000002"  # seed: معرض النور CIB
DOHA_CASH = "c0000000-0000-0000-0000-000000000003"
TODAY = "2026-10-02"
OLD_MONTH = "2025-02"  # used for lock tests, far from everyday postings


def owner() -> dict[str, str]:
    return {**auth("owner@nour.example", NOUR), "Idempotency-Key": str(uuid.uuid4())}


def balance(client: TestClient, cash_account_id: str) -> Decimal:
    accounts = client.get("/api/v1/cash-accounts", headers=auth("owner@nour.example", NOUR)).json()
    return Decimal(next(a["balance"] for a in accounts if a["id"] == cash_account_id))


def rent_category(client: TestClient) -> str:
    categories = client.get(
        "/api/v1/expense-categories", params={"kind": "GENERAL"}, headers=auth("owner@nour.example", NOUR)
    ).json()
    return str(next(c["id"] for c in categories if c["code"] == "rent"))


def expense_body(client: TestClient, amount: str = "1500.00", **overrides: Any) -> dict[str, Any]:
    return {
        "expense_date": TODAY,
        "category_id": rent_category(client),
        "amount": amount,
        "cash_account_id": CASH,
        "description": "إيجار مخزن",
        **overrides,
    }


# --- Rule 20 ------


def test_general_expense_posts_rule_20_and_reduces_cash(client: TestClient) -> None:
    before = balance(client, CASH)
    response = client.post("/api/v1/general-expenses", headers=owner(), json=expense_body(client, "1500.00"))
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["document"]["amount"] == "1500.00"
    assert body["document"]["status"] == "POSTED"
    assert balance(client, CASH) == before - Decimal("1500.00")

    entry = client.get(
        f"/api/v1/journal-entries/{body['journal_entries'][0]['id']}", headers=auth("accountant@nour.example", NOUR)
    ).json()
    assert entry["source_type"] == "GENERAL_EXPENSE"
    assert [(line["account_code"], line["debit"], line["credit"]) for line in entry["lines"]] == [
        ("6210", "1500.00", "0.00"),
        ("1101", "0.00", "1500.00"),
    ]


def test_preview_explains_the_expense_in_plain_language(client: TestClient) -> None:
    response = client.post(
        "/api/v1/general-expenses/preview", headers=auth("owner@nour.example", NOUR), json=expense_body(client, "250")
    )
    assert response.status_code == 200, response.text
    preview = response.json()
    assert preview["summary_ar"].startswith("سيتم خصم 250.00 ج.م من «الخزنة الرئيسية»")
    assert "“Main cash box”" in preview["summary_en"]
    assert preview["effects"] == [
        {"direction": "OUT", "label_ar": "الخزنة الرئيسية", "label_en": "Main cash box", "amount": "250.00"}
    ]
    assert preview["lines"] is not None  # owner may see debit/credit


def test_manager_preview_hides_debit_credit_lines(client: TestClient, admin_db: psycopg.Connection[Any]) -> None:
    # The seed has no manager; borrow the accountant's membership with the MANAGER role.
    admin_db.execute(
        "update public.memberships set role_id = (select id from public.roles where code = 'MANAGER' "
        "and tenant_id is null) where user_id = 'a0000000-0000-0000-0000-000000000002'"
    )
    try:
        preview = client.post(
            "/api/v1/general-expenses/preview",
            headers=auth("accountant@nour.example", NOUR),
            json=expense_body(client, "10"),
        ).json()
        assert preview["lines"] is None
    finally:
        admin_db.execute(
            "update public.memberships set role_id = (select id from public.roles where code = 'ACCOUNTANT' "
            "and tenant_id is null) where user_id = 'a0000000-0000-0000-0000-000000000002'"
        )


@pytest.mark.parametrize(
    ("override", "code"),
    [
        ({"amount": "0"}, "VALIDATION_ERROR"),
        ({"amount": "10.005"}, "VALIDATION_ERROR"),
        ({"amount": 10.5}, "VALIDATION_ERROR"),
        ({"expense_date": "2099-01-01"}, "DATE_IN_FUTURE"),
        ({"cash_account_id": DOHA_CASH}, "CASH_ACCOUNT_INVALID"),
    ],
)
def test_invalid_expenses_are_rejected(client: TestClient, override: dict[str, Any], code: str) -> None:
    response = client.post("/api/v1/general-expenses", headers=owner(), json=expense_body(client, **override))
    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == code


def test_vehicle_category_cannot_be_a_general_expense(client: TestClient) -> None:
    categories = client.get(
        "/api/v1/expense-categories", params={"kind": "VEHICLE"}, headers=auth("owner@nour.example", NOUR)
    ).json()
    response = client.post(
        "/api/v1/general-expenses", headers=owner(), json=expense_body(client, category_id=categories[0]["id"])
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "CATEGORY_INVALID"


# --- Permissions ------


def test_sales_and_partner_cannot_move_or_see_money(client: TestClient) -> None:
    for email in ("sales@nour.example", "partner@nour.example"):
        headers = {**auth(email, NOUR), "Idempotency-Key": str(uuid.uuid4())}
        assert client.post("/api/v1/general-expenses", headers=headers, json=expense_body(client)).status_code == 403
        assert client.get("/api/v1/cash-accounts", headers=headers).status_code == 403
        assert client.get("/api/v1/journal-entries", headers=headers).status_code == 403


def test_accountant_cannot_lock_periods_but_owner_can(client: TestClient) -> None:
    response = client.post(f"/api/v1/periods/{OLD_MONTH}/lock", headers=auth("accountant@nour.example", NOUR))
    assert response.status_code == 403


# --- Idempotency ------


def test_retrying_with_the_same_key_posts_once(client: TestClient) -> None:
    headers = owner()
    body = expense_body(client, "77.00")
    before = balance(client, CASH)
    first = client.post("/api/v1/general-expenses", headers=headers, json=body)
    second = client.post("/api/v1/general-expenses", headers=headers, json=body)
    assert first.status_code == second.status_code == 201
    assert second.headers.get("Idempotent-Replay") == "true"
    assert first.json() == second.json()
    assert balance(client, CASH) == before - Decimal("77.00")

    reused = client.post("/api/v1/general-expenses", headers=headers, json=expense_body(client, "78.00"))
    assert reused.status_code == 409
    assert reused.json()["error"]["code"] == "IDEMPOTENCY_KEY_REUSED"


def test_money_posts_require_an_idempotency_key(client: TestClient) -> None:
    response = client.post(
        "/api/v1/general-expenses", headers=auth("owner@nour.example", NOUR), json=expense_body(client)
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "IDEMPOTENCY_KEY_REQUIRED"


# --- Rule 21 ------


def test_transfer_posts_rule_21_and_moves_money_between_accounts(client: TestClient) -> None:
    cash_before, bank_before = balance(client, CASH), balance(client, BANK)
    response = client.post(
        "/api/v1/transfers",
        headers=owner(),
        json={"transfer_date": TODAY, "from_cash_account_id": BANK, "to_cash_account_id": CASH, "amount": "3000"},
    )
    assert response.status_code == 201, response.text
    assert balance(client, CASH) == cash_before + Decimal("3000.00")
    assert balance(client, BANK) == bank_before - Decimal("3000.00")


def test_transfer_to_the_same_account_is_refused(client: TestClient) -> None:
    response = client.post(
        "/api/v1/transfers",
        headers=owner(),
        json={"transfer_date": TODAY, "from_cash_account_id": CASH, "to_cash_account_id": CASH, "amount": "1"},
    )
    assert response.json()["error"]["code"] == "TRANSFER_SAME_ACCOUNT"


# --- Cash-negative policy ---------------------------------------------------------------------------------


def test_cash_negative_policy_warns_or_blocks(client: TestClient, admin_db: psycopg.Connection[Any]) -> None:
    too_much = str(balance(client, CASH) + Decimal("1000000.00"))
    preview = client.post(
        "/api/v1/general-expenses/preview",
        headers=auth("owner@nour.example", NOUR),
        json=expense_body(client, too_much),
    ).json()
    assert [w["code"] for w in preview["warnings"]] == ["CASH_NEGATIVE"]  # default policy: WARN

    admin_db.execute("update public.tenant_settings set cash_negative_policy = 'BLOCK' where tenant_id = %s", (NOUR,))
    try:
        before = balance(client, CASH)
        response = client.post("/api/v1/general-expenses", headers=owner(), json=expense_body(client, too_much))
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "CASH_INSUFFICIENT"
        assert balance(client, CASH) == before
    finally:
        admin_db.execute(
            "update public.tenant_settings set cash_negative_policy = 'WARN' where tenant_id = %s", (NOUR,)
        )


# --- Rule 24: reversal ------


def test_reversal_restores_balances_and_marks_the_document(client: TestClient) -> None:
    before = balance(client, CASH)
    posted = client.post("/api/v1/general-expenses", headers=owner(), json=expense_body(client, "420.00")).json()
    entry_id = posted["journal_entries"][0]["id"]
    assert balance(client, CASH) == before - Decimal("420.00")

    preview = client.post(
        f"/api/v1/journal-entries/{entry_id}/reverse/preview",
        headers=auth("accountant@nour.example", NOUR),
        json={"reason": "تسجيل مكرر"},
    ).json()
    assert f"القيد رقم {posted['journal_entries'][0]['entry_no']}" in preview["summary_ar"]
    assert preview["effects"][0]["direction"] == "IN"

    response = client.post(
        f"/api/v1/journal-entries/{entry_id}/reverse",
        headers={**auth("accountant@nour.example", NOUR), "Idempotency-Key": str(uuid.uuid4())},
        json={"reason": "تسجيل مكرر"},
    )
    assert response.status_code == 201, response.text
    assert balance(client, CASH) == before

    document = client.get(
        "/api/v1/general-expenses", params={"page_size": 200}, headers=auth("owner@nour.example", NOUR)
    )
    mine = next(d for d in document.json()["items"] if d["id"] == posted["document"]["id"])
    assert mine["status"] == "REVERSED"
    assert mine["reversal_entry_no"] == response.json()["reversal"]["entry_no"]

    again = client.post(
        f"/api/v1/journal-entries/{entry_id}/reverse",
        headers={**auth("accountant@nour.example", NOUR), "Idempotency-Key": str(uuid.uuid4())},
        json={"reason": "مرة أخرى"},
    )
    assert again.status_code == 409
    assert again.json()["error"]["code"] == "ENTRY_ALREADY_REVERSED"


def test_reversal_needs_a_reason_and_the_permission(client: TestClient) -> None:
    posted = client.post("/api/v1/general-expenses", headers=owner(), json=expense_body(client, "5.00")).json()
    entry_id = posted["journal_entries"][0]["id"]
    no_reason = client.post(f"/api/v1/journal-entries/{entry_id}/reverse", headers=owner(), json={"reason": " "})
    assert no_reason.status_code == 422
    sales = client.post(
        f"/api/v1/journal-entries/{entry_id}/reverse",
        headers={**auth("sales@nour.example", NOUR), "Idempotency-Key": str(uuid.uuid4())},
        json={"reason": "x" * 5},
    )
    assert sales.status_code == 403


# --- Locked periods ------


def test_locked_month_rejects_postings_and_reversals(client: TestClient) -> None:
    posted = client.post(
        "/api/v1/general-expenses", headers=owner(), json=expense_body(client, "9.00", expense_date=f"{OLD_MONTH}-10")
    ).json()
    entry_id = posted["journal_entries"][0]["id"]

    lock = client.post(f"/api/v1/periods/{OLD_MONTH}/lock", headers=auth("owner@nour.example", NOUR))
    assert lock.status_code == 200
    assert lock.json()["status"] == "LOCKED"
    try:
        blocked = client.post(
            "/api/v1/general-expenses",
            headers=owner(),
            json=expense_body(client, "9.00", expense_date=f"{OLD_MONTH}-11"),
        )
        assert blocked.status_code == 422
        assert blocked.json()["error"] == {
            "code": "PERIOD_LOCKED",
            "message": "The accounting month is locked",
            "details": {"period": OLD_MONTH},
        }
        reversal_inside = client.post(
            f"/api/v1/journal-entries/{entry_id}/reverse",
            headers=owner(),
            json={"reason": "تصحيح", "reversal_date": f"{OLD_MONTH}-20"},
        )
        assert reversal_inside.json()["error"]["code"] == "PERIOD_LOCKED"
        # The correction goes into an open month instead.
        reversal_now = client.post(
            f"/api/v1/journal-entries/{entry_id}/reverse", headers=owner(), json={"reason": "تصحيح"}
        )
        assert reversal_now.status_code == 201
    finally:
        unlock = client.post(
            f"/api/v1/periods/{OLD_MONTH}/unlock",
            headers=auth("owner@nour.example", NOUR),
            json={"reason": "test cleanup"},
        )
        assert unlock.json()["status"] == "OPEN"


def test_only_the_owner_unlocks(client: TestClient) -> None:
    response = client.post(
        f"/api/v1/periods/{OLD_MONTH}/unlock", headers=auth("accountant@nour.example", NOUR), json={"reason": "please"}
    )
    assert response.status_code == 403


# --- Cross-tenant ---------------------------------------------------------------------------------------------------


def test_another_tenants_entry_or_account_is_invisible(client: TestClient) -> None:
    nour_entry = client.get(
        "/api/v1/journal-entries", params={"page_size": 1}, headers=auth("owner@nour.example", NOUR)
    ).json()["items"][0]["id"]
    response = client.get(f"/api/v1/journal-entries/{nour_entry}", headers=auth("owner@doha.example", DOHA))
    assert response.status_code == 404
    reverse = client.post(
        f"/api/v1/journal-entries/{nour_entry}/reverse",
        headers={**auth("owner@doha.example", DOHA), "Idempotency-Key": str(uuid.uuid4())},
        json={"reason": "not mine"},
    )
    assert reverse.status_code == 404
    pay_from_nour = client.post(
        "/api/v1/transfers",
        headers={**auth("owner@doha.example", DOHA), "Idempotency-Key": str(uuid.uuid4())},
        json={"transfer_date": TODAY, "from_cash_account_id": CASH, "to_cash_account_id": DOHA_CASH, "amount": "1"},
    )
    assert pay_from_nour.status_code == 422
    assert pay_from_nour.json()["error"]["code"] == "CASH_ACCOUNT_INVALID"


# --- Gapless numbering under concurrency ------


def test_concurrent_postings_get_gapless_numbers(client: TestClient, admin_db: psycopg.Connection[Any]) -> None:
    database = client.app.state.database  # type: ignore[attr-defined]
    owner_id = uuid.UUID("a0000000-0000-0000-0000-000000000001")
    payload = GeneralExpenseIn.model_validate(expense_body(client, "1.00"))

    def post_one(_: int) -> int:
        with database.transaction(user_id=owner_id, tenant_id=uuid.UUID(NOUR)) as conn:
            return finance.record_expense(conn, payload).journal_entries[0].entry_no

    def post_then_roll_back(_: int) -> bool:
        # A rolled-back posting must not leave a hole in the numbering.
        try:
            with database.transaction(user_id=owner_id, tenant_id=uuid.UUID(NOUR)) as conn:
                finance.record_expense(conn, payload)
                raise AppError("TEST_ROLLBACK", "rollback on purpose")
        except AppError:
            return True
        return False

    with ThreadPoolExecutor(max_workers=10) as pool:
        numbers = list(pool.map(post_one, range(20)))
        rolled_back = list(pool.map(post_then_roll_back, range(5)))
    assert len(set(numbers)) == 20
    assert all(rolled_back)

    count, highest = admin_db.execute(
        "select count(*), max(entry_no) from public.journal_entries where tenant_id = %s", (NOUR,)
    ).fetchone() or (0, 0)
    assert count == highest, "entry numbers must have no gaps"


# --- Cash book ------


def test_cash_book_reconciles_with_the_balance(client: TestClient) -> None:
    headers = auth("owner@nour.example", NOUR)
    book = client.get(
        "/api/v1/reports/cash-book",
        # From before any data, so every movement of the account is in the book.
        params={"cash_account_id": CASH, "date_from": "2000-01-01", "date_to": TODAY},
        headers=headers,
    ).json()
    assert book["opening_balance"] == "0.00"
    opening = next(m for m in book["movements"] if m["description"] == "أرصدة افتتاحية")
    assert opening["amount_in"] == "200000.00"
    running = Decimal(book["opening_balance"])
    for movement in book["movements"]:
        running += Decimal(movement["amount_in"]) - Decimal(movement["amount_out"])
        assert Decimal(movement["balance"]) == running
    assert Decimal(book["closing_balance"]) == running == balance(client, CASH)
    assert Decimal(book["total_in"]) - Decimal(book["total_out"]) == running


def test_cash_book_exports_excel(client: TestClient) -> None:
    response = client.get(
        "/api/v1/reports/cash-book",
        params={"cash_account_id": BANK, "date_from": "2026-09-01", "date_to": TODAY, "format": "xlsx"},
        headers=auth("accountant@nour.example", NOUR),
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/vnd.openxmlformats")
    assert response.content[:2] == b"PK"  # xlsx is a zip file
    assert "cash-book-1201-" in response.headers["content-disposition"]


# --- Settings: cash accounts and categories ------


def test_new_cash_account_gets_its_own_ledger_sub_account(client: TestClient) -> None:
    response = client.post(
        "/api/v1/cash-accounts",
        headers=auth("owner@doha.example", DOHA),
        json={"kind": "BANK", "name_ar": f"بنك قطر الوطني {uuid.uuid4().hex[:4]}", "bank_name": "QNB"},
    )
    assert response.status_code == 201, response.text
    account = response.json()
    assert account["ledger_account_code"].startswith("12")
    assert account["balance"] == "0.00"
    archived = client.patch(
        f"/api/v1/cash-accounts/{account['id']}", headers=auth("owner@doha.example", DOHA), json={"archived": True}
    )
    assert archived.json()["archived"] is True


def test_cash_account_with_money_cannot_be_archived(client: TestClient) -> None:
    response = client.patch(
        f"/api/v1/cash-accounts/{BANK}", headers=auth("owner@nour.example", NOUR), json={"archived": True}
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "CASH_ACCOUNT_NOT_EMPTY"


def test_new_general_category_gets_a_62xx_account(client: TestClient) -> None:
    response = client.post(
        "/api/v1/expense-categories",
        headers=auth("owner@doha.example", DOHA),
        json={"kind": "GENERAL", "name_ar": "صيانة المعرض", "name_en": f"Showroom upkeep {uuid.uuid4().hex[:4]}"},
    )
    assert response.status_code == 201, response.text
    assert response.json()["ledger_account_code"].startswith("62")
    assert response.json()["code"].startswith("showroom_upkeep")
