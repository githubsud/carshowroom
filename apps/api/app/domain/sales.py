"""Request and response models for reservations (deposits) and sales (SPEC §4.7)."""

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.domain.installments import InstallmentPlanIn
from app.domain.money import Money, PositiveMoney
from app.domain.vehicles import Fuel, NoteText, ReasonText, ShortText, Transmission, VinText

ReservationStatus = Literal["ACTIVE", "RELEASED", "APPLIED", "REFUNDED", "FORFEITED"]
SaleStatus = Literal["DRAFT", "POSTED", "CANCELLED"]
CancellationMethod = Literal["REFUND_LIABILITY", "MIRROR"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


# --- Reservations (rules 11, 34, 35) -----------------------------------------------------


class ReservationIn(StrictModel):
    vehicle_id: UUID
    customer_id: UUID
    reservation_date: date
    deposit_amount: PositiveMoney
    cash_account_id: UUID
    expires_on: date | None = None
    notes: NoteText | None = None


class ReservationSettleIn(StrictModel):
    action: Literal["REFUND", "FORFEIT"]
    settle_date: date
    # Required for a refund: where the money is paid from.
    cash_account_id: UUID | None = None


class ReservationOut(BaseModel):
    id: UUID
    vehicle_id: UUID
    stock_no: str
    vehicle_label: str
    customer_id: UUID
    customer_name: str
    reservation_date: date
    deposit_amount: Money
    cash_account_id: UUID
    expires_on: date | None
    expired: bool
    status: ReservationStatus
    settled_on: date | None
    entry_no: int
    sale_id: UUID | None


# --- Sales --------------------------------------------------------------------------------------


class SalePaymentIn(StrictModel):
    cash_account_id: UUID
    amount: PositiveMoney
    payment_method_id: UUID | None = None
    reference: Annotated[str, StringConstraints(strip_whitespace=True, max_length=120)] | None = None


class TradeInIn(StrictModel):
    """The buyer's own car taken as part payment (rule 26)."""

    make: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
    model: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
    year: int | None = Field(default=None, ge=1950, le=2100)
    vin: VinText | None = None
    plate_no: ShortText | None = None
    color_ext: ShortText | None = None
    mileage_km: int | None = Field(default=None, ge=0, le=5_000_000)
    transmission: Transmission | None = None
    fuel: Fuel | None = None
    agreed_value: PositiveMoney


class SaleDraftIn(StrictModel):
    vehicle_id: UUID
    buyer_customer_id: UUID
    sale_date: date
    list_price: PositiveMoney
    discount: Money = Decimal(0)
    reservation_id: UUID | None = None
    payments: list[SalePaymentIn] = Field(default_factory=list, max_length=6)
    trade_in: TradeInIn | None = None
    # Whatever payments, deposit and trade-in leave open, paid by installments (rule 13, mode a).
    installments: InstallmentPlanIn | None = None
    notes: NoteText | None = None


class SaleCancelIn(StrictModel):
    cancel_date: date | None = None
    reason: ReasonText


class SalePaymentOut(BaseModel):
    cash_account_id: UUID
    cash_account_name_ar: str
    cash_account_name_en: str | None
    payment_method_id: UUID | None
    amount: Money
    reference: str | None


class SaleProfit(BaseModel):
    cost: Money
    gross_profit: Money
    profit_pct: Decimal


class SaleOut(BaseModel):
    id: UUID
    sale_no: str
    status: SaleStatus
    vehicle_id: UUID
    stock_no: str
    vehicle_label: str
    buyer_customer_id: UUID
    buyer_name: str
    buyer_phone: str | None
    sale_date: date
    list_price: Money
    discount: Money
    sale_price: Money
    reservation_id: UUID | None
    deposit_applied: Money
    trade_in: TradeInIn | None
    trade_in_value: Money
    trade_in_vehicle_id: UUID | None
    payments: list[SalePaymentOut]
    paid_total: Money
    installment_plan: InstallmentPlanIn | None
    # Financed by installments: what payments, deposit and trade-in leave open, when a plan is set.
    financed: Money
    plan_id: UUID | None
    # Still to be covered before the sale can be posted (sale price - paid - deposit - trade-in - financed).
    remaining: Money
    invoice_no: str | None
    einvoice_status: str
    entry_no: int | None
    cost_entry_no: int | None
    cancellation_method: CancellationMethod | None
    cancel_date: date | None
    cancel_reason: str | None
    created_at: datetime
    created_by_me: bool
    notes: str | None
    profit: SaleProfit | None = None


class SaleListRow(BaseModel):
    id: UUID
    sale_no: str
    status: SaleStatus
    vehicle_id: UUID
    stock_no: str
    vehicle_label: str
    buyer_name: str
    sale_date: date
    sale_price: Money
    invoice_no: str | None


class SalePage(BaseModel):
    items: list[SaleListRow]
    page: int
    page_size: int
    total: int
