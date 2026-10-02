"""Posting rules (docs/ACCOUNTING.md §3). Pure functions: command in, balanced
draft out. Unit-tested in tests/unit/test_posting_rules.py.

Implemented so far: 20 (general expense), 21 (cash <-> bank transfer),
24 (reversal; the database performs it, this mirror is used for previews and
cash checks). Further rules arrive with their phases (BACKLOG).
"""

from collections.abc import Iterable
from dataclasses import replace
from datetime import date
from decimal import Decimal
from uuid import UUID

from app.domain.ledger import ZERO, Account, CashAccountRef, EntryDraft, LedgerRuleError, Line
from app.domain.money import CENT


def _positive_amount(amount: Decimal) -> Decimal:
    if amount <= 0:
        raise LedgerRuleError("amount must be greater than zero")
    if amount != amount.quantize(CENT):
        raise LedgerRuleError("amount has more than 2 decimals")
    return amount


def general_expense(
    *,
    entry_date: date,
    amount: Decimal,
    expense_account: Account,
    paid_from: CashAccountRef,
    description: str,
    source_id: UUID | None,
) -> EntryDraft:
    """Rule 20 — general expense paid in cash or by bank:
    Dr expense category account / Cr cash or bank."""
    amount = _positive_amount(amount)
    draft = EntryDraft(
        entry_date=entry_date,
        description=description,
        source_type="GENERAL_EXPENSE",
        source_id=source_id,
        lines=(
            Line(account=expense_account, debit=amount),
            Line(account=paid_from.account, credit=amount, cash_account_id=paid_from.cash_account_id),
        ),
    )
    draft.validate()
    return draft


def transfer(
    *,
    entry_date: date,
    amount: Decimal,
    source: CashAccountRef,
    destination: CashAccountRef,
    description: str,
    source_id: UUID | None,
) -> EntryDraft:
    """Rule 21 — cash <-> bank transfer: Dr destination / Cr source."""
    amount = _positive_amount(amount)
    if source.cash_account_id == destination.cash_account_id:
        raise LedgerRuleError("cannot transfer to the same account")
    draft = EntryDraft(
        entry_date=entry_date,
        description=description,
        source_type="TRANSFER",
        source_id=source_id,
        lines=(
            Line(account=destination.account, debit=amount, cash_account_id=destination.cash_account_id),
            Line(account=source.account, credit=amount, cash_account_id=source.cash_account_id),
        ),
    )
    draft.validate()
    return draft


def reversal_lines(original: Iterable[Line]) -> tuple[Line, ...]:
    """Rule 24 — the exact mirror: every debit becomes a credit and vice versa,
    with the same accounts, subledger ids and memos, in the same order."""
    mirrored = tuple(replace(line, debit=line.credit, credit=line.debit) for line in original)
    if sum((line.debit for line in mirrored), ZERO) != sum((line.credit for line in mirrored), ZERO):
        raise LedgerRuleError("original entry does not balance")
    return mirrored
