"""Report models (SPEC §4.12).

Every report is also a ``ReportTable``: one generic shape that the web app
renders and that the exporters write to PDF and Excel, so each report gets
both formats from the same numbers.
"""

from datetime import date
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.domain.money import Money

ColumnKind = Literal["text", "money", "date", "number", "percent"]
RowStyle = Literal["section", "total", "muted"]
ReportName = Literal[
    "profit-and-loss",
    "trial-balance",
    "general-ledger",
    "balance-check",
    "vehicle-profit",
    "inventory-aging",
    "expenses-by-category",
    "installment-collections",
    "deferred-papers",
    "consignments-in",
    "consignments-out",
]


class ReportColumn(BaseModel):
    key: str
    label_ar: str
    label_en: str
    kind: ColumnKind = "text"


class ReportRow(BaseModel):
    cells: dict[str, str | int | None]
    style: RowStyle | None = None
    # Deep link for the web app, e.g. ["vehicles", "<id>"].
    link: list[str] | None = None


class ReportTable(BaseModel):
    name: ReportName
    title_ar: str
    title_en: str
    period_ar: str | None = None
    period_en: str | None = None
    currency_code: str
    columns: list[ReportColumn]
    rows: list[ReportRow]
    # Headline figures shown above the table: (label_ar, label_en, value, kind).
    figures: list[tuple[str, str, str, ColumnKind]] = Field(default_factory=list)


# --- Financial ----------------------------------------------------------------------------------------


class AccountAmount(BaseModel):
    account_id: UUID
    code: str
    name_ar: str
    name_en: str
    amount: Money


class ProfitAndLoss(BaseModel):
    """Owner-friendly P&L (SPEC §4.12 #10); closing entries are left out (D-29)."""

    date_from: date
    date_to: date
    revenue: list[AccountAmount]
    revenue_total: Money
    cost_of_sales: Money
    gross_profit: Money
    expenses: list[AccountAmount]
    expenses_total: Money
    net_profit: Money


class TrialBalanceRow(BaseModel):
    account_id: UUID
    code: str
    name_ar: str
    name_en: str
    type: str
    debit: Money
    credit: Money


class TrialBalance(BaseModel):
    as_of: date
    rows: list[TrialBalanceRow]
    total_debit: Money
    total_credit: Money


class LedgerLine(BaseModel):
    entry_date: date
    entry_no: int
    description: str
    debit: Money
    credit: Money
    balance: Money


class GeneralLedger(BaseModel):
    account_id: UUID
    code: str
    name_ar: str
    name_en: str
    date_from: date
    date_to: date
    opening: Money
    lines: list[LedgerLine]
    closing: Money


class BalanceCheck(BaseModel):
    """Assets = liabilities + equity + profit not yet closed (C-07)."""

    as_of: date
    assets: Money
    liabilities: Money
    equity: Money
    unclosed_profit: Money
    difference: Money
    balanced: bool
    opening_equity: Money
    notes: list[str]


ReportFormat = Literal["json", "pdf", "xlsx"]


class ReportFilters(BaseModel):
    date_from: date | None = None
    date_to: date | None = None
    as_of: date | None = None
    account_id: UUID | None = None


def money_text(value: Decimal) -> str:
    return f"{value:.2f}"
