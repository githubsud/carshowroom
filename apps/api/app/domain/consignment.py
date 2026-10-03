"""Consignment in and out, external showrooms (SPEC §4.4, §4.5), follow-ups
and customer requests with matching (SPEC §4.6).

Pure helpers for the commission terms and the owner's share of an expense are
unit-tested in tests/unit/test_consignment_rules.py.
"""

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from app.domain.ledger import ZERO
from app.domain.money import Money, PositiveMoney, quantize
from app.domain.vehicles import NameText, NoteText, PhoneInput, ReasonText, ShortText, StrictModel, VehicleIn

TermsType = Literal["NET_PRICE", "COMMISSION_FIXED", "COMMISSION_PCT"]
ExpensesBorneBy = Literal["OWNER", "SHOWROOM", "SHARED"]
ConsignmentInStatus = Literal["ACTIVE", "SOLD", "RETURNED"]
ConsignmentOutStatus = Literal["OUT", "SOLD", "RETURNED"]
ExternalCommissionType = Literal["FIXED", "PCT"]
SettlementKind = Literal["PAYOUT", "RECOVERY"]
RequestStatus = Literal["NEW", "CONTACTED", "VEHICLE_FOUND", "NEGOTIATING", "DEPOSIT", "WON", "LOST", "ON_HOLD"]
FollowUpKind = Literal["CALL", "VISIT", "TEST_DRIVE", "NOTE"]
FollowUpResult = Literal["ANSWERED", "NO_ANSWER", "INTERESTED", "NOT_INTERESTED", "CALL_BACK", "OTHER"]
Priority = Literal["LOW", "NORMAL", "HIGH"]
Percent = Annotated[Decimal, Field(gt=0, le=100, max_digits=5, decimal_places=2)]
YearValue = Annotated[int, Field(ge=1950, le=2100)]
OPEN_REQUEST_STATUSES = ("NEW", "CONTACTED", "VEHICLE_FOUND", "NEGOTIATING")

_HUNDRED = Decimal(100)


class CommissionError(ValueError):
    """A sale price the agreement does not allow; `code` is the API error code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def commission_for(
    terms: TermsType, sale_price: Decimal, *, net_price: Decimal | None, value: Decimal | None
) -> Decimal:
    """The showroom's commission on a consigned-in car (SPEC §4.4).

    NET_PRICE: the sale price minus the agreed net to the owner; a sale at or
    below the net is blocked (Q-15 default). COMMISSION_FIXED: the agreed amount.
    COMMISSION_PCT: the percentage of the sale price, half-up to the cent (A-07).
    """
    if terms == "NET_PRICE":
        if net_price is None:
            raise CommissionError("CONSIGNMENT_TERMS_INVALID", "the agreement has no net price")
        if sale_price <= net_price:
            raise CommissionError("SALE_BELOW_NET_PRICE", "the sale price must be above the owner's net price")
        return quantize(sale_price - net_price)
    if value is None:
        raise CommissionError("CONSIGNMENT_TERMS_INVALID", "the agreement has no commission")
    commission = quantize(value if terms == "COMMISSION_FIXED" else sale_price * value / _HUNDRED)
    if commission >= sale_price:
        raise CommissionError("COMMISSION_EXCEEDS_PRICE", "the commission must be less than the sale price")
    return commission


def external_commission_for(kind: ExternalCommissionType, sale_price: Decimal, value: Decimal) -> Decimal:
    """What an external showroom keeps when it sells our car (rule 18)."""
    commission = quantize(value if kind == "FIXED" else sale_price * value / _HUNDRED)
    if commission >= sale_price:
        raise CommissionError("COMMISSION_EXCEEDS_PRICE", "the commission must be less than the sale price")
    return commission


def owner_share(amount: Decimal, borne_by: ExpensesBorneBy, owner_pct: Decimal | None) -> Decimal:
    """The part of an expense the owner repays (rule 10); the rest is the showroom's (P-05)."""
    if borne_by == "OWNER":
        return amount
    if borne_by == "SHOWROOM":
        return ZERO
    if owner_pct is None:
        raise ValueError("a shared agreement needs the owner's percentage")
    return quantize(amount * owner_pct / _HUNDRED)


# --- External showrooms ----------------------------------------------------------------------------------


class ExternalShowroomIn(StrictModel):
    name: NameText
    contact_name: NameText | None = None
    phone: PhoneInput | None = None
    address: NoteText | None = None
    notes: NoteText | None = None


class ExternalShowroomUpdate(StrictModel):
    name: NameText | None = None
    contact_name: NameText | None = None
    phone: PhoneInput | None = None
    address: NoteText | None = None
    notes: NoteText | None = None
    archived: bool | None = None


class ExternalShowroomOut(BaseModel):
    id: UUID
    name: str
    contact_name: str | None
    phone: str | None
    address: str | None
    notes: str | None
    archived: bool
    cars_out: int
    # Only with consignment.settle.
    receivable: Money | None = None


# --- Consignment IN ------------------------------------------------------------------------------------


class _Terms(StrictModel):
    agreement_date: date
    end_date: date | None = None
    terms_type: TermsType
    net_price_to_owner: PositiveMoney | None = None
    commission_value: PositiveMoney | None = None
    expenses_borne_by: ExpensesBorneBy = "OWNER"
    shared_owner_pct: Percent | None = None
    notes: NoteText | None = None

    @model_validator(mode="after")
    def _consistent(self) -> "_Terms":
        if (self.terms_type == "NET_PRICE") != (self.net_price_to_owner is not None):
            raise ValueError("a net price is given exactly for net-price terms")
        if (self.terms_type != "NET_PRICE") != (self.commission_value is not None):
            raise ValueError("a commission is given exactly for commission terms")
        if self.terms_type == "COMMISSION_PCT" and self.commission_value is not None and self.commission_value > 100:
            raise ValueError("a percentage cannot exceed 100")
        if (self.expenses_borne_by == "SHARED") != (self.shared_owner_pct is not None):
            raise ValueError("the owner's percentage is given exactly for shared expenses")
        if self.shared_owner_pct is not None and self.shared_owner_pct >= 100:
            raise ValueError("a shared percentage must be below 100")
        if self.end_date is not None and self.end_date < self.agreement_date:
            raise ValueError("the agreement cannot end before it starts")
        return self


class ConsignmentIn(_Terms):
    """Receive a consigned car: the vehicle record and the agreement together."""

    consignor_id: UUID
    vehicle: VehicleIn


class ConsignmentUpdate(_Terms):
    """New terms for an ACTIVE agreement (before the car is sold)."""


class ConsignmentReturnIn(StrictModel):
    return_date: date
    reason: ReasonText


class ConsignorSettlementIn(StrictModel):
    kind: SettlementKind
    settle_date: date
    amount: PositiveMoney
    cash_account_id: UUID
    notes: NoteText | None = None


class ConsignorSettlementOut(BaseModel):
    id: UUID
    kind: SettlementKind
    settle_date: date
    amount: Money
    cash_account_name_ar: str
    status: Literal["POSTED", "REVERSED"]
    entry_no: int
    notes: str | None


class ConsignmentOut(BaseModel):
    id: UUID
    vehicle_id: UUID
    stock_no: str
    vehicle_label: str
    vehicle_status: str
    consignor_id: UUID
    consignor_name: str
    consignor_phone: str | None
    agreement_date: date
    end_date: date | None
    expired: bool
    terms_type: TermsType
    net_price_to_owner: Money | None
    commission_value: Money | None
    expenses_borne_by: ExpensesBorneBy
    shared_owner_pct: Decimal | None
    asking_price: Money | None
    status: ConsignmentInStatus
    returned_date: date | None
    days_with_us: int | None
    notes: str | None
    sale_id: UUID | None = None
    sale_no: str | None = None
    sale_price: Money | None = None
    # Money with the owner: only with consignment.settle.
    commission: Money | None = None
    payable: Money | None = None
    recoverable: Money | None = None
    settlements: list[ConsignorSettlementOut] | None = None


class StatementLine(BaseModel):
    entry_date: date
    entry_no: int
    description: str
    stock_no: str | None
    debit: Money
    credit: Money
    balance: Money


class ConsignorStatement(BaseModel):
    """What the showroom owes the owner (2200) less what the owner owes back (1430)."""

    consignor_id: UUID
    consignor_name: str
    consignor_phone: str | None
    as_of: date
    currency_code: str
    lines: list[StatementLine]
    payable: Money
    recoverable: Money
    net_due_to_owner: Money
    consignments: list[ConsignmentOut]


# --- Consignment OUT -------------------------------------------------------------------------------------


class ConsignOutIn(StrictModel):
    vehicle_id: UUID
    external_showroom_id: UUID
    sent_date: date
    commission_type: ExternalCommissionType
    commission_value: Annotated[Decimal, Field(ge=0, max_digits=18, decimal_places=2)]
    expected_price: PositiveMoney | None = None
    notes: NoteText | None = None

    @model_validator(mode="after")
    def _pct(self) -> "ConsignOutIn":
        if self.commission_type == "PCT" and self.commission_value > 100:
            raise ValueError("a percentage cannot exceed 100")
        return self


class ConsignOutReturnIn(StrictModel):
    return_date: date
    reason: NoteText | None = None


class ExternalSaleIn(StrictModel):
    sale_date: date
    sale_price: PositiveMoney
    buyer_name: NameText | None = None
    notes: NoteText | None = None


class ConsignmentOutOut(BaseModel):
    id: UUID
    vehicle_id: UUID
    stock_no: str
    vehicle_label: str
    vehicle_status: str
    external_showroom_id: UUID
    external_showroom_name: str
    sent_date: date
    days_out: int | None
    commission_type: ExternalCommissionType
    commission_value: Decimal
    expected_price: Money | None
    status: ConsignmentOutStatus
    returned_date: date | None
    sale_id: UUID | None
    sale_no: str | None
    sale_price: Money | None
    notes: str | None


class ExternalCollectionIn(StrictModel):
    collect_date: date
    amount: PositiveMoney
    cash_account_id: UUID
    notes: NoteText | None = None


class ExternalCollectionOut(BaseModel):
    id: UUID
    collect_date: date
    amount: Money
    cash_account_name_ar: str
    status: Literal["POSTED", "REVERSED"]
    entry_no: int
    notes: str | None


class ExternalShowroomStatement(BaseModel):
    external_showroom_id: UUID
    name: str
    phone: str | None
    as_of: date
    currency_code: str
    lines: list[StatementLine]
    receivable: Money
    cars: list[ConsignmentOutOut]
    collections: list[ExternalCollectionOut]


# --- Customer requests and matching (SPEC §4.6) ------------------------------------------------------------


class _RequestFields(StrictModel):
    make: ShortText | None = None
    model: ShortText | None = None
    year_from: YearValue | None = None
    year_to: YearValue | None = None
    budget_min: Annotated[Decimal, Field(ge=0, max_digits=18, decimal_places=2)] | None = None
    budget_max: Annotated[Decimal, Field(ge=0, max_digits=18, decimal_places=2)] | None = None
    color_pref: ShortText | None = None
    notes: NoteText | None = None
    assigned_to: UUID | None = None
    source: ShortText | None = None
    financing_needed: bool | None = None
    trade_in_offered: bool | None = None

    @model_validator(mode="after")
    def _ranges(self) -> "_RequestFields":
        if self.year_from is not None and self.year_to is not None and self.year_from > self.year_to:
            raise ValueError("year from must not be after year to")
        if self.budget_min is not None and self.budget_max is not None and self.budget_min > self.budget_max:
            raise ValueError("the minimum budget must not exceed the maximum")
        return self


class CustomerRequestIn(_RequestFields):
    customer_id: UUID

    @model_validator(mode="after")
    def _something_wanted(self) -> "CustomerRequestIn":
        if self.make is None and self.model is None:
            raise ValueError("give at least a make or a model")
        return self


class CustomerRequestUpdate(_RequestFields):
    status: RequestStatus | None = None


class RequestMatch(BaseModel):
    id: UUID
    request_id: UUID
    vehicle_id: UUID
    stock_no: str
    vehicle_label: str
    vehicle_status: str
    asking_price: Money | None
    customer_id: UUID
    customer_name: str
    customer_phone: str | None
    request_summary: str
    matched_at: datetime
    contacted: bool
    contacted_at: datetime | None


class CustomerRequestOut(BaseModel):
    id: UUID
    customer_id: UUID
    customer_name: str
    customer_phone: str | None
    make: str | None
    model: str | None
    year_from: int | None
    year_to: int | None
    budget_min: Money | None
    budget_max: Money | None
    color_pref: str | None
    notes: str | None
    status: RequestStatus
    assigned_to: UUID | None
    assigned_name: str | None
    source: str | None
    financing_needed: bool
    trade_in_offered: bool
    created_at: datetime
    match_count: int
    matches: list[RequestMatch] = Field(default_factory=list)


# --- Follow-ups (D-22) --------------------------------------------------------------------------------------


class FollowUpIn(StrictModel):
    customer_id: UUID
    request_id: UUID | None = None
    kind: FollowUpKind = "CALL"
    result: FollowUpResult | None = None
    notes: NoteText | None = None
    next_action: NoteText | None = None
    next_follow_up_date: date | None = None
    assigned_to: UUID | None = None
    priority: Priority = "NORMAL"


class FollowUpOut(BaseModel):
    id: UUID
    customer_id: UUID
    customer_name: str
    customer_phone: str | None
    request_id: UUID | None
    kind: FollowUpKind
    occurred_at: datetime
    result: FollowUpResult | None
    notes: str | None
    next_action: str | None
    next_follow_up_date: date | None
    assigned_to: UUID | None
    assigned_name: str | None
    priority: Priority
    created_by_name: str | None


class FollowUpDue(BaseModel):
    """A customer whose latest follow-up asks to be called back by today."""

    follow_up: FollowUpOut
    overdue_days: int
