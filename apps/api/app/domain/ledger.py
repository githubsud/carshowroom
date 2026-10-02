"""Journal entry drafts: what posting rules produce and the engine posts.

A draft is validated here with the same rules the database enforces
(supabase/migrations/*_journal.sql), so mistakes surface as clear errors
before reaching Postgres. The database remains the final guard.
"""

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

from app.domain.money import CENT, to_cents_string

ZERO = Decimal(0)


class LedgerRuleError(ValueError):
    """A posting rule or draft is invalid (programming or input error)."""


@dataclass(frozen=True)
class Account:
    """A ledger account, either a tenant account id or a chart-of-accounts system key."""

    ledger_account_id: UUID | None = None
    system_key: str | None = None

    @staticmethod
    def by_id(ledger_account_id: UUID) -> "Account":
        return Account(ledger_account_id=ledger_account_id)

    @staticmethod
    def system(system_key: str) -> "Account":
        return Account(system_key=system_key)

    def resolve(self, system_accounts: dict[str, UUID]) -> UUID:
        if self.ledger_account_id is not None:
            return self.ledger_account_id
        if self.system_key in system_accounts:
            return system_accounts[self.system_key]
        raise LedgerRuleError(f"unknown system account {self.system_key}")


@dataclass(frozen=True)
class CashAccountRef:
    """A cash box or bank account and its own ledger sub-account."""

    cash_account_id: UUID
    ledger_account_id: UUID

    @property
    def account(self) -> Account:
        return Account.by_id(self.ledger_account_id)


_SUBLEDGERS = (
    "cash_account_id",
    "partner_id",
    "customer_id",
    "vehicle_id",
    "consignor_id",
    "external_showroom_id",
    "supplier_id",
)


@dataclass(frozen=True)
class Line:
    account: Account
    debit: Decimal = ZERO
    credit: Decimal = ZERO
    cash_account_id: UUID | None = None
    partner_id: UUID | None = None
    customer_id: UUID | None = None
    vehicle_id: UUID | None = None
    consignor_id: UUID | None = None
    external_showroom_id: UUID | None = None
    supplier_id: UUID | None = None
    memo: str | None = None

    def validate(self) -> None:
        for side in (self.debit, self.credit):
            if side < 0:
                raise LedgerRuleError("amounts cannot be negative")
            if side != side.quantize(CENT):
                raise LedgerRuleError("amounts have at most 2 decimals")
        if (self.debit > 0) == (self.credit > 0):
            raise LedgerRuleError("each line has exactly one of debit or credit")

    def to_payload(self, system_accounts: dict[str, UUID]) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "ledger_account_id": str(self.account.resolve(system_accounts)),
            "debit": to_cents_string(self.debit),
            "credit": to_cents_string(self.credit),
        }
        for name in _SUBLEDGERS:
            value = getattr(self, name)
            if value is not None:
                payload[name] = str(value)
        if self.memo:
            payload["memo"] = self.memo
        return payload


@dataclass(frozen=True)
class EntryDraft:
    entry_date: date
    description: str
    source_type: str
    source_id: UUID | None
    lines: tuple[Line, ...]
    is_opening: bool = field(default=False)

    def validate(self) -> None:
        if len(self.lines) < 2:
            raise LedgerRuleError("an entry needs at least two lines")
        if not self.description.strip():
            raise LedgerRuleError("an entry needs a description")
        for line in self.lines:
            line.validate()
        debit = sum((line.debit for line in self.lines), ZERO)
        credit = sum((line.credit for line in self.lines), ZERO)
        if debit != credit:
            raise LedgerRuleError(f"entry does not balance: debit {debit} credit {credit}")

    def cash_effects(self) -> dict[UUID, Decimal]:
        """Net change per cash/bank account (positive = money in)."""
        effects: dict[UUID, Decimal] = {}
        for line in self.lines:
            if line.cash_account_id is not None:
                effects[line.cash_account_id] = effects.get(line.cash_account_id, ZERO) + line.debit - line.credit
        return effects

    def to_payload(self, system_accounts: dict[str, UUID]) -> dict[str, Any]:
        self.validate()
        return {
            "entry_date": self.entry_date.isoformat(),
            "description": self.description.strip(),
            "source_type": self.source_type,
            "source_id": str(self.source_id) if self.source_id else None,
            "is_opening": self.is_opening,
            "lines": [line.to_payload(system_accounts) for line in self.lines],
        }
