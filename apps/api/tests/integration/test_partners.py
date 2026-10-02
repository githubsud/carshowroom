"""Phase 3 acceptance: the owner can answer "what is each partner's balance?" in
one screen, matching hand-calculated values (SPEC §13)."""

import uuid
from datetime import date
from decimal import Decimal
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient

from app.domain.finance import GeneralExpenseIn, OtherIncomeIn
from app.domain.partners import PartnerTransactionIn, ShareChangeIn
from app.services import finance, partners
from tests.integration.conftest import DOHA, NOUR, auth

DOHA_CASH = "c0000000-0000-0000-0000-000000000003"
NOUR_BANK = "c0000000-0000-0000-0000-000000000002"
KHALID = uuid.UUID("f0000000-0000-0000-0000-000000000011")
YOUSEF_DOHA = uuid.UUID("f0000000-0000-0000-0000-000000000013")
AHMED = "f0000000-0000-0000-0000-000000000001"
MONA = "f0000000-0000-0000-0000-000000000002"
YOUSEF = "f0000000-0000-0000-0000-000000000003"
TODAY = "2026-10-02"


class _Rollback(Exception):
    """Raised on purpose so the scenario leaves no trace."""


def owner(tenant: str = NOUR) -> dict[str, str]:
    email = "owner@nour.example" if tenant == NOUR else "owner@doha.example"
    return {**auth(email, tenant), "Idempotency-Key": str(uuid.uuid4())}


# --- The hand-calculated scenario ---------------------------------------------------------------


def test_partner_balances_match_hand_calculation(client: TestClient) -> None:
    """Doha Motors, Khalid 70% / Youssef 30%, all on 2026-10-01 (amounts in QAR):

       1  Khalid contributes                1,000,000  cash +1,000,000   capital K  1,000,000
       3  Khalid draws                         50,000  cash    -50,000   current K    -50,000  (warning)
       4  loan to Youssef                      30,000  cash    -30,000   loans to Y    30,000
       5  Youssef repays                       10,000  cash    +10,000   loans to Y    20,000
      28  Youssef lends the showroom          100,000  cash   +100,000   loans from Y 100,000
      29  showroom repays Youssef              40,000  cash    -40,000   loans from Y  60,000
      30  Khalid pays rent personally (CA)      3,000  cash          0   current K     -47,000
       2  Khalid withdraws capital            100,000  cash   -100,000   capital K    900,000
    P-01  other income (commission)             5,000  cash     +5,000

     Expected: Khalid  capital 900,000, current -47,000, drawings 50,000, net 853,000
               Youssef loans to 20,000, loans from 60,000, net 40,000
               cash +895,000 over the opening balance
    """
    database = client.app.state.database  # type: ignore[attr-defined]
    owner_id = uuid.UUID("b0000000-0000-0000-0000-000000000001")
    day = date(2026, 10, 1)
    cash = uuid.UUID(DOHA_CASH)

    def txn(conn: Any, partner: uuid.UUID, kind: str, amount: str) -> Any:
        payload = PartnerTransactionIn.model_validate(
            {"type": kind, "txn_date": day, "amount": amount, "cash_account_id": cash}
        )
        return partners.record_transaction(conn, partner, payload)

    def scenario() -> None:
        with database.transaction(user_id=owner_id, tenant_id=uuid.UUID(DOHA)) as conn:
            cash_before = finance.get_cash_account(conn, cash).balance

            txn(conn, KHALID, "CONTRIBUTION", "1000000")
            drawing = txn(conn, KHALID, "DRAWING", "50000")
            txn(conn, YOUSEF_DOHA, "LOAN_TO_PARTNER", "30000")
            txn(conn, YOUSEF_DOHA, "LOAN_TO_PARTNER_REPAYMENT", "10000")
            txn(conn, YOUSEF_DOHA, "LOAN_FROM_PARTNER", "100000")
            txn(conn, YOUSEF_DOHA, "LOAN_FROM_PARTNER_REPAYMENT", "40000")
            rent = next(c for c in finance.list_categories(conn, "GENERAL", False) if c.code == "rent")
            finance.record_expense(
                conn,
                GeneralExpenseIn.model_validate(
                    {
                        "expense_date": day,
                        "category_id": rent.id,
                        "amount": "3000",
                        "paid_by_partner_id": KHALID,
                        "partner_funding_mode": "CURRENT_ACCOUNT",
                    }
                ),
            )
            txn(conn, KHALID, "CAPITAL_WITHDRAWAL", "100000")
            finance.record_income(
                conn,
                OtherIncomeIn.model_validate(
                    {
                        "income_date": day,
                        "amount": "5000",
                        "cash_account_id": cash,
                        "description": "عمولة وساطة",
                    }
                ),
            )

            assert [w.code for w in drawing.warnings] == ["DRAWING_EXCEEDS_BALANCE"]

            summary = partners.summary(conn, day)
            rows = {row.partner_id: row for row in summary.rows}
            khalid, youssef = rows[KHALID], rows[YOUSEF_DOHA]
            assert (khalid.percentage, khalid.capital, khalid.current, khalid.drawings, khalid.net) == (
                Decimal("70.0000"),
                Decimal("900000.00"),
                Decimal("-47000.00"),
                Decimal("50000.00"),
                Decimal("853000.00"),
            )
            assert (youssef.percentage, youssef.loans_to_partner, youssef.loans_from_partner, youssef.net) == (
                Decimal("30.0000"),
                Decimal("20000.00"),
                Decimal("60000.00"),
                Decimal("40000.00"),
            )
            assert summary.totals.net == Decimal("893000.00")
            assert finance.get_cash_account(conn, cash).balance - cash_before == Decimal("895000.00")

            statement = partners.statement(conn, KHALID, day, day)
            assert statement.opening.net == Decimal("0.00")
            assert [(line.bucket, line.amount_in, line.amount_out) for line in statement.lines] == [
                ("CAPITAL", Decimal("1000000.00"), Decimal("0.00")),
                ("CURRENT", Decimal("0.00"), Decimal("50000.00")),
                ("CURRENT", Decimal("3000.00"), Decimal("0.00")),
                ("CAPITAL", Decimal("0.00"), Decimal("100000.00")),
            ]
            assert statement.lines[-1].running_net == statement.closing.net == Decimal("853000.00")

            # Ownership history: Youssef leaves from November, Khalid holds 100%.
            partners.change_shares(
                conn,
                ShareChangeIn.model_validate(
                    {"effective_from": "2026-11-01", "shares": [{"partner_id": KHALID, "percentage": "100"}]}
                ),
            )
            assert [(s.partner_id, s.percentage) for s in partners.shares_on(conn, date(2026, 11, 1))] == [
                (KHALID, Decimal("100.0000"))
            ]
            assert {s.partner_id for s in partners.shares_on(conn, date(2026, 10, 31))} == {KHALID, YOUSEF_DOHA}
            raise _Rollback

    with pytest.raises(_Rollback):
        scenario()


# --- Summary and statement through the API -------------------------------------------------------


def test_owner_sees_every_partner_balance_in_one_screen(client: TestClient) -> None:
    response = client.get("/api/v1/partners/summary", params={"as_of": TODAY}, headers=auth("owner@nour.example", NOUR))
    assert response.status_code == 200, response.text
    body = response.json()
    rows = {row["name_ar"]: row for row in body["rows"]}
    assert {name: row["percentage"] for name, row in rows.items()} == {
        "أحمد السيد": "50.0000",
        "منى عبد الله": "30.0000",
        "يوسف حسن": "20.0000",
    }
    # Seed: contributions 500,000 / 300,000 / 200,000; later tests may add movements, never to capital here.
    assert Decimal(rows["أحمد السيد"]["capital"]) >= Decimal("500000.00")
    assert body["totals"]["percentage"] == "100.0000"


def test_statement_for_a_partner(client: TestClient) -> None:
    response = client.get(
        f"/api/v1/partners/{MONA}/statement",
        params={"date_from": "2026-09-01", "date_to": TODAY},
        headers=auth("accountant@nour.example", NOUR),
    )
    assert response.status_code == 200, response.text
    statement = response.json()
    assert statement["opening"]["net"] == "0.00"
    first = statement["lines"][0]
    assert (first["bucket"], first["amount_in"], first["entry_date"]) == ("CAPITAL", "300000.00", "2026-09-02")

    xlsx = client.get(
        f"/api/v1/partners/{MONA}/statement",
        params={"date_from": "2026-09-01", "date_to": TODAY, "format": "xlsx"},
        headers=auth("accountant@nour.example", NOUR),
    )
    assert xlsx.status_code == 200
    assert xlsx.content[:2] == b"PK"


# --- Partner role: own statement only ---------------------------------------------------------------


def test_partner_user_sees_only_their_own_statement(client: TestClient, admin_db: psycopg.Connection[Any]) -> None:
    headers = auth("partner@nour.example", NOUR)
    params = {"date_from": "2026-09-01", "date_to": TODAY}
    own = client.get(f"/api/v1/partners/{YOUSEF}/statement", params=params, headers=headers)
    assert own.status_code == 200
    assert own.json()["partner"]["name_ar"] == "يوسف حسن"
    other = client.get(f"/api/v1/partners/{AHMED}/statement", params=params, headers=headers)
    assert other.status_code == 403
    assert client.get("/api/v1/partners", headers=headers).status_code == 403

    # The summary only when the showroom allows it.
    assert client.get("/api/v1/partners/summary", headers=headers).status_code == 403
    admin_db.execute("update public.tenant_settings set partner_sees_summary = true where tenant_id = %s", (NOUR,))
    try:
        assert client.get("/api/v1/partners/summary", headers=headers).status_code == 200
    finally:
        admin_db.execute("update public.tenant_settings set partner_sees_summary = false where tenant_id = %s", (NOUR,))


def test_sales_has_no_access_to_partners(client: TestClient) -> None:
    headers = auth("sales@nour.example", NOUR)
    assert client.get("/api/v1/partners/summary", headers=headers).status_code == 403
    assert (
        client.get(
            f"/api/v1/partners/{AHMED}/statement", params={"date_from": "2026-01-01", "date_to": TODAY}, headers=headers
        ).status_code
        == 403
    )


# --- Transactions through the API ---------------------------------------------------------------------


def test_drawing_posts_rule_3_with_the_partner_subledger(client: TestClient) -> None:
    preview = client.post(
        f"/api/v1/partners/{MONA}/transactions/preview",
        headers=auth("owner@nour.example", NOUR),
        json={"type": "DRAWING", "txn_date": TODAY, "amount": "1000", "cash_account_id": NOUR_BANK},
    ).json()
    assert preview["summary_ar"].startswith("سيتم خصم 1,000.00 ج.م من «بنك CIB» وتسجيلها كـمسحوبات من الحصة")

    response = client.post(
        f"/api/v1/partners/{MONA}/transactions",
        headers=owner(),
        json={"type": "DRAWING", "txn_date": TODAY, "amount": "1000", "cash_account_id": NOUR_BANK},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert "DRAWING_EXCEEDS_BALANCE" in [w["code"] for w in body["warnings"]]
    entry = client.get(
        f"/api/v1/journal-entries/{body['journal_entries'][0]['id']}", headers=auth("accountant@nour.example", NOUR)
    ).json()
    assert [(line["account_code"], line["debit"], line["credit"]) for line in entry["lines"]] == [
        ("3200", "1000.00", "0.00"),
        ("1201", "0.00", "1000.00"),
    ]

    # Reversal marks the partner transaction.
    client.post(
        f"/api/v1/journal-entries/{body['journal_entries'][0]['id']}/reverse",
        headers=owner(),
        json={"reason": "مكرر"},
    )
    history = client.get(f"/api/v1/partners/{MONA}/transactions", headers=auth("owner@nour.example", NOUR)).json()
    assert next(t for t in history if t["id"] == body["document"]["id"])["status"] == "REVERSED"


def test_capital_withdrawal_needs_the_equity_permission(client: TestClient) -> None:
    response = client.post(
        f"/api/v1/partners/{MONA}/transactions",
        headers={**auth("accountant@nour.example", NOUR), "Idempotency-Key": str(uuid.uuid4())},
        json={"type": "CAPITAL_WITHDRAWAL", "txn_date": TODAY, "amount": "1", "cash_account_id": NOUR_BANK},
    )
    assert response.status_code == 403
    assert response.json()["error"]["details"]["permission"] == "partner.equity.change"


def test_repayment_cannot_exceed_what_is_owed(client: TestClient) -> None:
    response = client.post(
        f"/api/v1/partners/{MONA}/transactions",
        headers=owner(),
        json={
            "type": "LOAN_TO_PARTNER_REPAYMENT",
            "txn_date": TODAY,
            "amount": "999999999",
            "cash_account_id": NOUR_BANK,
        },
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "REPAYMENT_EXCEEDS_LOAN"


def test_expense_paid_personally_does_not_touch_cash(client: TestClient) -> None:
    accounts = client.get("/api/v1/cash-accounts", headers=auth("owner@nour.example", NOUR)).json()
    before = {a["id"]: a["balance"] for a in accounts}
    rent = next(
        c
        for c in client.get(
            "/api/v1/expense-categories", params={"kind": "GENERAL"}, headers=auth("owner@nour.example", NOUR)
        ).json()
        if c["code"] == "rent"
    )
    response = client.post(
        "/api/v1/general-expenses",
        headers=owner(),
        json={
            "expense_date": TODAY,
            "category_id": rent["id"],
            "amount": "750",
            "paid_by_partner_id": AHMED,
            "partner_funding_mode": "LOAN",
        },
    )
    assert response.status_code == 201, response.text
    assert response.json()["document"]["paid_by_partner_name_ar"] == "أحمد السيد"
    after = {
        a["id"]: a["balance"]
        for a in client.get("/api/v1/cash-accounts", headers=auth("owner@nour.example", NOUR)).json()
    }
    assert after == before

    both = client.post(
        "/api/v1/general-expenses",
        headers=owner(),
        json={
            "expense_date": TODAY,
            "category_id": rent["id"],
            "amount": "1",
            "cash_account_id": NOUR_BANK,
            "paid_by_partner_id": AHMED,
            "partner_funding_mode": "LOAN",
        },
    )
    assert both.status_code == 422


def test_other_income_posts_p01(client: TestClient) -> None:
    response = client.post(
        "/api/v1/other-incomes",
        headers=owner(),
        json={"income_date": TODAY, "amount": "2500", "cash_account_id": NOUR_BANK, "description": "عمولة وساطة"},
    )
    assert response.status_code == 201, response.text
    entry = client.get(
        f"/api/v1/journal-entries/{response.json()['journal_entries'][0]['id']}",
        headers=auth("accountant@nour.example", NOUR),
    ).json()
    assert [(line["account_code"], line["debit"], line["credit"]) for line in entry["lines"]] == [
        ("1201", "2500.00", "0.00"),
        ("4900", "0.00", "2500.00"),
    ]


# --- Ownership changes ------------------------------------------------------------------------------------


def test_share_changes_must_total_100_and_move_forward(client: TestClient) -> None:
    headers = auth("owner@nour.example", NOUR)
    short = client.post(
        "/api/v1/partners/shares",
        headers=headers,
        json={
            "effective_from": "2027-01-01",
            "shares": [{"partner_id": AHMED, "percentage": "60"}, {"partner_id": MONA, "percentage": "30"}],
        },
    )
    assert short.status_code == 422
    assert short.json()["error"] == {
        "code": "SHARES_NOT_100",
        "message": "Ownership must total exactly 100%",
        "details": {"total": "90.0000"},
    }
    backdated = client.post(
        "/api/v1/partners/shares",
        headers=headers,
        json={"effective_from": "2025-06-01", "shares": [{"partner_id": AHMED, "percentage": "100"}]},
    )
    assert backdated.json()["error"]["code"] == "SHARE_DATE_INVALID"
    accountant = client.post(
        "/api/v1/partners/shares",
        headers=auth("accountant@nour.example", NOUR),
        json={"effective_from": "2027-01-01", "shares": [{"partner_id": AHMED, "percentage": "100"}]},
    )
    assert accountant.status_code == 403


# --- National ID (encrypted, masked, audited) ----------------------------------------------------------------


def test_national_id_is_encrypted_masked_and_audited(client: TestClient, admin_db: psycopg.Connection[Any]) -> None:
    created = client.post(
        "/api/v1/partners",
        headers=auth("owner@doha.example", DOHA),
        json={"name_ar": f"شريك جديد {uuid.uuid4().hex[:4]}", "national_id": "29001011234567"},
    )
    assert created.status_code == 201, created.text
    partner = created.json()
    assert partner["national_id_masked"] == "••••4567"
    assert partner["percentage"] == "0"

    stored = admin_db.execute(
        "select national_id_enc, national_id_last4 from public.partners where id = %s", (partner["id"],)
    ).fetchone()
    assert stored is not None
    assert "29001011234567" not in stored[0]
    assert stored[1] == "4567"

    revealed = client.get(f"/api/v1/partners/{partner['id']}/national-id", headers=auth("owner@doha.example", DOHA))
    assert revealed.json() == {"national_id": "29001011234567"}
    event = admin_db.execute(
        "select count(*) from public.audit_log where action = 'NATIONAL_ID_VIEWED' and entity_id = %s",
        (partner["id"],),
    ).fetchone()
    assert event == (1,)

    # A partner with no share and no balance can leave.
    archived = client.patch(
        f"/api/v1/partners/{partner['id']}", headers=auth("owner@doha.example", DOHA), json={"archived": True}
    )
    assert archived.json()["archived"] is True


def test_partner_with_a_balance_cannot_be_archived(client: TestClient) -> None:
    response = client.patch(
        f"/api/v1/partners/{MONA}", headers=auth("owner@nour.example", NOUR), json={"archived": True}
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "PARTNER_NOT_SETTLED"


# --- Linking users to partners ------------------------------------------------------------------------------


def test_a_partner_record_links_to_one_user(client: TestClient) -> None:
    users = client.get("/api/v1/users", headers=auth("owner@nour.example", NOUR)).json()
    accountant = next(m for m in users if m["email"] == "accountant@nour.example")
    taken = client.patch(
        f"/api/v1/users/{accountant['membership_id']}",
        headers=auth("owner@nour.example", NOUR),
        json={"partner_id": YOUSEF},  # already linked to partner@nour.example
    )
    assert taken.status_code == 409
    assert taken.json()["error"]["code"] == "PARTNER_ALREADY_LINKED"
