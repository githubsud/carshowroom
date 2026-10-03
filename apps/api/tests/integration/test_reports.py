"""Phase 7 through the API on the seed data: reports centre (JSON and Excel),
Needs Attention and the dashboard, each filtered by permission."""

from io import BytesIO
from typing import Any

from fastapi.testclient import TestClient
from openpyxl import load_workbook

from tests.integration.conftest import NOUR, auth


def _owner() -> dict[str, str]:
    return auth("owner@nour.example", NOUR)


def _sales() -> dict[str, str]:
    return auth("sales@nour.example", NOUR)


def _kinds(items: list[dict[str, Any]]) -> set[str]:
    return {item["kind"] for item in items}


def test_owner_sees_every_report_and_sales_only_operational_ones(client: TestClient) -> None:
    owner = client.get("/api/v1/reports", headers=_owner()).json()
    assert "profit-and-loss" in owner
    assert "vehicle-profit" in owner
    sales = client.get("/api/v1/reports", headers=_sales()).json()
    assert "vehicle-profit" not in sales
    assert "profit-and-loss" not in sales
    denied = client.get("/api/v1/reports/vehicle-profit", headers=_sales())
    assert denied.status_code == 403


def test_seed_profit_and_loss_and_balance_check(client: TestClient) -> None:
    pnl = client.get(
        "/api/v1/reports/profit-and-loss",
        params={"date_from": "2026-09-01", "date_to": "2026-09-30"},
        headers=_owner(),
    ).json()
    totals = {row["cells"]["name"]: row["cells"]["amount"] for row in pnl["rows"] if row["style"] == "total"}
    # Seed (BACKLOG Phase 4/5): Sunny 260,000 - 228,000 and Optra 200,000 - 150,000; rent 25,000.
    assert totals["إجمالي الإيرادات|Total revenue"] == "460000.00"
    assert totals["مجمل الربح|Gross profit"] == "82000.00"
    assert totals["صافي الربح|Net profit"] == "57000.00"

    check = client.get("/api/v1/reports/balance-check", params={"as_of": "2026-09-30"}, headers=_owner()).json()
    assert check["figures"][0][2] == "✓"


def test_reports_export_to_excel(client: TestClient) -> None:
    response = client.get("/api/v1/reports/inventory-aging", params={"format": "xlsx", "lang": "ar"}, headers=_owner())
    assert response.status_code == 200
    sheet = load_workbook(BytesIO(response.content)).active
    assert sheet is not None
    assert sheet["A1"].value == "أعمار المخزون"


def test_trial_balance_balances(client: TestClient) -> None:
    tb = client.get("/api/v1/reports/trial-balance", headers=_owner()).json()
    total = tb["rows"][-1]["cells"]
    assert total["debit"] == total["credit"]


def test_attention_follows_permissions(client: TestClient) -> None:
    # A call-back due today (the seed's own may already be answered by other tests).
    customer = client.post("/api/v1/customers", headers=_owner(), json={"name": "عميل متابعة"}).json()["id"]
    today = client.get("/api/v1/dashboard", headers=_owner()).json()["as_of"]
    client.post(
        "/api/v1/follow-ups",
        headers=_owner(),
        json={"customer_id": customer, "result": "CALL_BACK", "next_follow_up_date": today},
    )
    owner = client.get("/api/v1/attention", headers=_owner()).json()
    kinds = _kinds(owner)
    # Seed: Omar's first installment is overdue and Sara's request matches the Corolla.
    assert {"INSTALLMENT_OVERDUE", "FOLLOW_UP_DUE", "REQUEST_MATCH"} <= kinds
    severities = [item["severity"] for item in owner]
    assert severities == sorted(severities, key=["danger", "warn", "info"].index)

    sales = client.get("/api/v1/attention", headers=_sales()).json()
    assert not _kinds(sales) & {
        "LOW_PROFIT",
        "COST_INCOMPLETE",
        "CASH_NEGATIVE",
        "PARTNER_OVERDRAWN",
        "SUPPLIER_PAYABLE",
    }


def test_dashboard_blocks_by_role(client: TestClient) -> None:
    owner = client.get("/api/v1/dashboard", headers=_owner()).json()
    assert owner["kpis"]["cash_total"] is not None
    assert owner["kpis"]["stock_cost"] is not None
    assert [row["percentage"] for row in owner["equity"]] == ["50.0000", "30.0000", "20.0000"]
    assert owner["attention"]

    sales = client.get("/api/v1/dashboard", headers=_sales()).json()
    assert sales["kpis"]["cash_total"] is None
    assert sales["kpis"].get("stock_cost") is None
    assert sales["kpis"].get("month_gross_profit") is None
    assert sales["equity"] is None
    assert sales["kpis"]["stock_count"] == owner["kpis"]["stock_count"]
