"""Request and response models for cash, bank, expenses, transfers, journal and periods."""

from datetime import date, datetime
from typing import Annotated, Generic, Literal, TypeVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.domain.money import Money, PositiveMoney

T = TypeVar("T")

NameText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
NoteText = Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)]
ReasonText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=500)]
CashKind = Literal["CASH_BOX", "BANK"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Page(BaseModel, Generic[T]):
    items: list[T]
    page: int
    page_size: int
    total: int


class PostingWarning(BaseModel):
    code: str
    details: dict[str, object] = Field(default_factory=dict)


class EntryRef(BaseModel):
    id: UUID
    entry_no: int


# --- Cash and bank accounts ---------------------------------------------------------


class CashAccountIn(StrictModel):
    kind: CashKind
    name_ar: NameText
    name_en: NameText | None = None
    bank_name: NameText | None = None
    account_number: NameText | None = None
    iban: Annotated[str, StringConstraints(strip_whitespace=True, pattern=r"^[A-Z]{2}[0-9A-Z]{10,32}$")] | None = None
    is_default: bool = False


class CashAccountUpdate(StrictModel):
    name_ar: NameText | None = None
    name_en: NameText | None = None
    bank_name: NameText | None = None
    account_number: NameText | None = None
    iban: Annotated[str, StringConstraints(strip_whitespace=True, pattern=r"^[A-Z]{2}[0-9A-Z]{10,32}$")] | None = None
    is_default: bool | None = None
    archived: bool | None = None


class CashAccountOut(BaseModel):
    id: UUID
    kind: CashKind
    name_ar: str
    name_en: str | None
    ledger_account_code: str
    bank_name: str | None
    account_number: str | None
    iban: str | None
    is_default: bool
    archived: bool
    balance: Money


# --- Expense categories and payment methods -------------------------------------------


class ExpenseCategoryIn(StrictModel):
    kind: Literal["VEHICLE", "GENERAL"]
    name_ar: NameText
    name_en: NameText


class ExpenseCategoryUpdate(StrictModel):
    name_ar: NameText | None = None
    name_en: NameText | None = None
    archived: bool | None = None


class ExpenseCategoryOut(BaseModel):
    id: UUID
    kind: Literal["VEHICLE", "GENERAL"]
    code: str
    name_ar: str
    name_en: str
    ledger_account_code: str | None
    is_seeded: bool
    archived: bool


class PaymentMethodOut(BaseModel):
    id: UUID
    code: str
    name_ar: str
    name_en: str
    default_cash_account_id: UUID | None


# --- Money-moving commands ---------------------------------------------------------------


class GeneralExpenseIn(StrictModel):
    expense_date: date
    category_id: UUID
    amount: PositiveMoney
    cash_account_id: UUID
    description: NoteText | None = None


class TransferIn(StrictModel):
    transfer_date: date
    from_cash_account_id: UUID
    to_cash_account_id: UUID
    amount: PositiveMoney
    notes: NoteText | None = None


class GeneralExpenseOut(BaseModel):
    id: UUID
    expense_date: date
    category_id: UUID
    category_name_ar: str
    category_name_en: str
    amount: Money
    description: str | None
    cash_account_id: UUID
    cash_account_name_ar: str
    cash_account_name_en: str | None
    status: Literal["POSTED", "REVERSED"]
    entry_no: int
    reversal_entry_no: int | None
    created_at: datetime


class TransferOut(BaseModel):
    id: UUID
    transfer_date: date
    from_cash_account_id: UUID
    from_name_ar: str
    from_name_en: str | None
    to_cash_account_id: UUID
    to_name_ar: str
    to_name_en: str | None
    amount: Money
    notes: str | None
    status: Literal["POSTED", "REVERSED"]
    entry_no: int
    reversal_entry_no: int | None
    created_at: datetime


class PostingResult(BaseModel, Generic[T]):
    document: T
    journal_entries: list[EntryRef]
    warnings: list[PostingWarning] = Field(default_factory=list)


# --- Plain-language preview (SPEC §9.3, D-31) ----------------------------------------------


class PreviewEffect(BaseModel):
    direction: Literal["IN", "OUT"]
    label_ar: str
    label_en: str
    amount: Money


class PreviewLine(BaseModel):
    account_code: str
    account_name_ar: str
    account_name_en: str
    debit: Money
    credit: Money


class Preview(BaseModel):
    summary_ar: str
    summary_en: str
    effects: list[PreviewEffect]
    warnings: list[PostingWarning] = Field(default_factory=list)
    # Debit/credit lines only for users who may see the journal (SPEC §9.3).
    lines: list[PreviewLine] | None = None


# --- Journal ------------------------------------------------------------------------------


class ReverseIn(StrictModel):
    reason: ReasonText
    reversal_date: date | None = None


class ReverseOut(BaseModel):
    original_entry_no: int
    reversal: EntryRef
    warnings: list[PostingWarning] = Field(default_factory=list)


class JournalLineOut(BaseModel):
    line_no: int
    account_code: str
    account_name_ar: str
    account_name_en: str
    debit: Money
    credit: Money
    cash_account_name_ar: str | None
    memo: str | None


class JournalEntryOut(BaseModel):
    id: UUID
    entry_no: int
    entry_date: date
    description: str
    source_type: str
    source_id: UUID | None
    total: Money
    reversal_of_entry_no: int | None
    reversed_by_entry_no: int | None
    reversal_reason: str | None
    is_opening: bool
    posted_at: datetime
    lines: list[JournalLineOut] | None = None


class LedgerAccountOut(BaseModel):
    id: UUID
    code: str
    parent_code: str | None
    name_ar: str
    name_en: str
    type: Literal["ASSET", "LIABILITY", "EQUITY", "INCOME", "EXPENSE"]
    normal_side: Literal["DEBIT", "CREDIT"]
    is_postable: bool
    subledger: str
    # In the account's normal direction (assets/expenses: debit - credit; others: credit - debit).
    balance: Money


# --- Periods --------------------------------------------------------------------------------


class PeriodOut(BaseModel):
    month: str  # "2026-10"
    status: Literal["OPEN", "LOCKED"]
    locked_at: datetime | None
    entry_count: int


class UnlockIn(StrictModel):
    reason: ReasonText


# --- Cash book --------------------------------------------------------------------------------


class CashBookMovement(BaseModel):
    entry_date: date
    entry_no: int
    description: str
    source_type: str
    counterpart_ar: str
    counterpart_en: str
    amount_in: Money
    amount_out: Money
    balance: Money
    is_reversal: bool
    reversed: bool


class CashBookOut(BaseModel):
    cash_account: CashAccountOut
    date_from: date
    date_to: date
    currency_code: str
    opening_balance: Money
    total_in: Money
    total_out: Money
    closing_balance: Money
    movements: list[CashBookMovement]
