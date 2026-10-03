"""Needs Attention alerts (SPEC §4.17) and the dashboard (SPEC §4.12 #1)."""

from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.domain.installments import InstallmentKpis
from app.domain.money import Money

Severity = Literal["danger", "warn", "info"]
AttentionKind = Literal[
    "INSTALLMENT_OVERDUE",
    "INSTALLMENT_DUE_SOON",
    "CHEQUE_BOUNCED",
    "VEHICLE_AGING",
    "LICENSE_EXPIRY",
    "COST_INCOMPLETE",
    "LOW_PROFIT",
    "REQUEST_MATCH",
    "FOLLOW_UP_DUE",
    "LEAD_IDLE",
    "CONSIGNOR_SETTLEMENT",
    "SUPPLIER_PAYABLE",
    "CASH_NEGATIVE",
    "PARTNER_OVERDRAWN",
]


class AttentionItem(BaseModel):
    """One deterministic alert. `params` fill the translated message; `link`
    is the route of the record (e.g. ["vehicles", "<id>"])."""

    kind: AttentionKind
    severity: Severity
    params: dict[str, str | int | None]
    entity_type: str | None = None
    entity_id: UUID | None = None
    link: list[str]


class KpiTiles(BaseModel):
    cash_total: Money | None = None
    bank_total: Money | None = None
    stock_count: int
    # Capital tied up in inventory: only with vehicle.view_cost.
    stock_cost: Money | None = None
    aged_count: int
    aged_days: int
    month_sales_count: int
    month_sales_total: Money | None = None
    month_gross_profit: Money | None = None


class EquityRow(BaseModel):
    partner_id: UUID
    name_ar: str
    name_en: str | None
    percentage: Decimal
    capital: Money
    allocated_profit: Money
    drawings: Money
    net: Money


class DashboardOut(BaseModel):
    """Blocks appear only for users who may see them (owner / partner / staff)."""

    as_of: str
    kpis: KpiTiles
    installments: InstallmentKpis | None = None
    attention: list[AttentionItem] = Field(default_factory=list)
    equity: list[EquityRow] | None = None
