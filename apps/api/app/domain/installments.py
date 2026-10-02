"""Request and response models for installments, receipts, deferred papers and
notifications (SPEC §4.8, §4.17)."""

from datetime import date, datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from app.domain.money import Money, PositiveMoney

NoteText = Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)]
ShortText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]
PlanFrequency = Literal["MONTHLY", "BIWEEKLY", "WEEKLY", "QUARTERLY", "MANUAL"]
InstallmentState = Literal["PAID", "OVERDUE", "DUE_TODAY", "UPCOMING", "CANCELLED"]
PaperType = Literal["PROMISSORY_NOTE", "PDC"]
PaperStatus = Literal["HELD", "DEPOSITED", "COLLECTED", "BOUNCED", "RETURNED", "DEFAULTED", "LEGAL"]
PaperAction = Literal["DEPOSIT", "COLLECT", "BOUNCE", "RETURN", "DEFAULT", "LEGAL"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


# --- Plans and schedules ------------------------------------------------------------------


class ScheduleRowIn(StrictModel):
    due_date: date
    amount: PositiveMoney


class ScheduleRowOut(BaseModel):
    seq: int
    due_date: date
    amount: Money


class InstallmentPlanIn(StrictModel):
    """How the rest of a sale price is paid (mode a, SPEC §4.8): an equal split
    by frequency, or a manual schedule that adds up exactly."""

    frequency: PlanFrequency = "MONTHLY"
    count: int | None = Field(default=None, ge=1, le=360)
    first_due_date: date | None = None
    schedule: list[ScheduleRowIn] | None = Field(default=None, max_length=360)

    @model_validator(mode="after")
    def _complete(self) -> "InstallmentPlanIn":
        if self.frequency == "MANUAL":
            if not self.schedule:
                raise ValueError("a manual plan needs its schedule")
        elif self.count is None or self.first_due_date is None:
            raise ValueError("give the number of installments and the first due date")
        return self


class SchedulePreviewIn(StrictModel):
    financed: PositiveMoney
    plan: InstallmentPlanIn


class InstallmentOut(BaseModel):
    id: UUID
    plan_id: UUID
    sale_id: UUID
    sale_no: str
    customer_id: UUID
    customer_name: str
    customer_phone: str | None
    stock_no: str
    vehicle_label: str
    seq: int
    due_date: date
    amount_due: Money
    paid: Money
    remaining: Money
    days_late: int
    state: InstallmentState
    customer_bounced: bool


class AllocationOut(BaseModel):
    seq: int
    amount: Money


class ReceiptOut(BaseModel):
    id: UUID
    receipt_date: date
    amount: Money
    source: Literal["CASH_ACCOUNT", "CREDIT", "PAPER"]
    cash_account_name_ar: str | None
    excess_to_credit: Money
    status: Literal["POSTED", "REVERSED", "BOUNCED"]
    entry_no: int
    allocations: list[AllocationOut]


class PaperEventOut(BaseModel):
    from_status: str | None
    to_status: str
    event_date: date
    note: str | None
    entry_no: int | None
    created_at: datetime


class PaperOut(BaseModel):
    id: UUID
    paper_type: PaperType
    number: str
    customer_id: UUID
    customer_name: str
    installment_id: UUID | None
    installment_seq: int | None
    sale_no: str | None
    amount: Money
    issue_date: date | None
    due_date: date
    status: PaperStatus
    overdue: bool
    storage_location: str | None
    drawer_bank: str | None
    drawer_branch: str | None
    account_holder: str | None
    notes: str | None
    events: list[PaperEventOut] = Field(default_factory=list)


class InstallmentPlanOut(BaseModel):
    id: UUID
    sale_id: UUID
    sale_no: str
    customer_id: UUID
    customer_name: str
    stock_no: str
    vehicle_label: str
    financed_amount: Money
    frequency: PlanFrequency
    installment_count: int
    first_due_date: date
    status: Literal["ACTIVE", "CANCELLED"]
    paid_total: Money
    remaining_total: Money
    overdue_total: Money
    installments: list[InstallmentOut]
    receipts: list[ReceiptOut]
    papers: list[PaperOut]


# --- Receipts (rule 15) -----------------------------------------------------------------------


class ReceiptIn(StrictModel):
    receipt_date: date
    amount: PositiveMoney
    source: Literal["CASH_ACCOUNT", "CREDIT"] = "CASH_ACCOUNT"
    cash_account_id: UUID | None = None
    # Only where the showroom allows it (D-41 ALLOW_AS_CREDIT): the excess becomes customer credit.
    keep_excess_as_credit: bool = False
    notes: NoteText | None = None

    @model_validator(mode="after")
    def _source(self) -> "ReceiptIn":
        if (self.source == "CASH_ACCOUNT") != (self.cash_account_id is not None):
            raise ValueError("a cash or bank receipt names its account; a credit receipt does not")
        return self


# --- Board and calendar -----------------------------------------------------------------------------


class CustomerOutstanding(BaseModel):
    customer_id: UUID
    customer_name: str
    customer_phone: str | None
    outstanding: Money
    overdue: Money
    bounced: bool


class InstallmentBoard(BaseModel):
    as_of: date
    due_today: Money
    due_soon: Money
    overdue: Money
    rows: list[InstallmentOut]
    customers: list[CustomerOutstanding]


class InstallmentKpis(BaseModel):
    """Dashboard tiles (C-09): due in 48 hours and in 7 days, overdue, bounced."""

    due_48h: Money
    due_48h_count: int
    due_7d: Money
    due_7d_count: int
    overdue: Money
    overdue_count: int
    bounced_count: int


# --- Deferred papers -----------------------------------------------------------------------------------


class PaperIn(StrictModel):
    paper_type: PaperType
    number: ShortText
    customer_id: UUID
    installment_id: UUID | None = None
    amount: PositiveMoney
    issue_date: date | None = None
    due_date: date
    storage_location: NoteText | None = None
    drawer_bank: NoteText | None = None
    drawer_branch: NoteText | None = None
    account_holder: NoteText | None = None
    notes: NoteText | None = None


class PaperActionIn(StrictModel):
    action: PaperAction
    action_date: date
    # COLLECT: the account the money arrives in.
    cash_account_id: UUID | None = None
    # BOUNCE after collection: bank charges (P-07), as an expense or recharged to the customer.
    bank_charges: PositiveMoney | None = None
    charge_customer: bool = False
    note: NoteText | None = None


# --- Notifications -------------------------------------------------------------------------------------


class NotificationOut(BaseModel):
    id: UUID
    kind: str
    params: dict[str, object]
    entity_type: str | None
    entity_id: UUID | None
    read: bool
    created_at: datetime


class NotificationPage(BaseModel):
    items: list[NotificationOut]
    unread: int


# --- Customer statement ----------------------------------------------------------------------------------


class CustomerInstallmentStatement(BaseModel):
    customer_id: UUID
    customer_name: str
    customer_phone: str | None
    as_of: date
    currency_code: str
    plans: list[InstallmentPlanOut]
    total_financed: Money
    total_paid: Money
    total_remaining: Money
    total_overdue: Money
