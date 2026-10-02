"""Request and response models for partners, ownership and partner money (SPEC §4.2)."""

from datetime import date
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

from app.domain.money import Money, PositiveMoney

NameText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
NoteText = Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)]
NationalId = Annotated[str, StringConstraints(strip_whitespace=True, pattern=r"^[0-9A-Za-z]{4,20}$")]
PhoneText = Annotated[str, StringConstraints(strip_whitespace=True, pattern=r"^\+?[0-9 ]{6,20}$")]

PartnerTransactionKind = Literal[
    "CONTRIBUTION",
    "CAPITAL_WITHDRAWAL",
    "DRAWING",
    "LOAN_TO_PARTNER",
    "LOAN_TO_PARTNER_REPAYMENT",
    "LOAN_FROM_PARTNER",
    "LOAN_FROM_PARTNER_REPAYMENT",
]
Bucket = Literal["CAPITAL", "CURRENT", "LOAN_TO", "LOAN_FROM"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


# --- Partners -------------------------------------------------------------------------


class PartnerIn(StrictModel):
    name_ar: NameText
    name_en: NameText | None = None
    phone: PhoneText | None = None
    national_id: NationalId | None = None
    notes: NoteText | None = None


class PartnerUpdate(StrictModel):
    name_ar: NameText | None = None
    name_en: NameText | None = None
    phone: PhoneText | None = None
    national_id: NationalId | None = None
    notes: NoteText | None = None
    archived: bool | None = None


class PartnerOut(BaseModel):
    id: UUID
    name_ar: str
    name_en: str | None
    phone: str | None
    national_id_masked: str | None
    notes: str | None
    archived: bool
    # Share on today's date (tenant timezone); 0 when the partner holds none.
    percentage: Decimal


class NationalIdOut(BaseModel):
    national_id: str


# --- Ownership ------------------------------------------------------------------------------


class ShareIn(StrictModel):
    partner_id: UUID
    percentage: Annotated[Decimal, Field(gt=0, le=100, max_digits=7, decimal_places=4)]


class ShareChangeIn(StrictModel):
    effective_from: date
    shares: list[ShareIn] = Field(min_length=1, max_length=50)

    @field_validator("shares")
    @classmethod
    def _unique_partners(cls, shares: list[ShareIn]) -> list[ShareIn]:
        if len({share.partner_id for share in shares}) != len(shares):
            raise ValueError("each partner may appear once")
        return shares


class ShareOut(BaseModel):
    partner_id: UUID
    partner_name_ar: str
    partner_name_en: str | None
    percentage: Decimal
    effective_from: date
    effective_to: date | None


# --- Partner money (rules 1-5, 28, 29) -------------------------------------------------------


class PartnerTransactionIn(StrictModel):
    type: PartnerTransactionKind
    txn_date: date
    amount: PositiveMoney
    cash_account_id: UUID
    notes: NoteText | None = None


class PartnerTransactionOut(BaseModel):
    id: UUID
    partner_id: UUID
    partner_name_ar: str
    type: PartnerTransactionKind
    txn_date: date
    amount: Money
    cash_account_id: UUID
    cash_account_name_ar: str
    notes: str | None
    status: Literal["POSTED", "REVERSED"]
    entry_no: int
    reversal_entry_no: int | None


# --- Position, statement, summary --------------------------------------------------------------


class PartnerPosition(BaseModel):
    """A partner's position with the showroom. Net = capital + current account
    + loans from the partner - loans to the partner (DECISIONS Q-17)."""

    capital: Money
    current: Money
    loans_to_partner: Money
    loans_from_partner: Money
    net: Money


class StatementLine(BaseModel):
    entry_date: date
    entry_no: int
    description: str
    source_type: str
    bucket: Bucket
    # In the partner's favour (credit) / against the partner (debit).
    amount_in: Money
    amount_out: Money
    running_net: Money
    is_reversal: bool
    reversed: bool


class PartnerStatementOut(BaseModel):
    partner: PartnerOut
    date_from: date
    date_to: date
    currency_code: str
    opening: PartnerPosition
    closing: PartnerPosition
    lines: list[StatementLine]


class PartnerSummaryRow(BaseModel):
    partner_id: UUID
    name_ar: str
    name_en: str | None
    percentage: Decimal
    capital: Money
    allocated_profit: Money
    drawings: Money
    current: Money
    loans_to_partner: Money
    loans_from_partner: Money
    net: Money


class PartnerSummaryOut(BaseModel):
    as_of: date
    currency_code: str
    rows: list[PartnerSummaryRow]
    totals: PartnerSummaryRow
