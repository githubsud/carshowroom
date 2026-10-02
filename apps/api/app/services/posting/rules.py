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
from typing import Literal
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


# --- Partners (rules 1-5, 28, 29) --------------------------------------------------------

PartnerTransactionKind = Literal[
    "CONTRIBUTION",
    "CAPITAL_WITHDRAWAL",
    "DRAWING",
    "LOAN_TO_PARTNER",
    "LOAN_TO_PARTNER_REPAYMENT",
    "LOAN_FROM_PARTNER",
    "LOAN_FROM_PARTNER_REPAYMENT",
]

# kind -> (partner account system key, money comes IN to the showroom?, source_type)
PARTNER_TRANSACTION_RULES: dict[PartnerTransactionKind, tuple[str, bool, str]] = {
    "CONTRIBUTION": ("PARTNER_CAPITAL", True, "PARTNER_CONTRIBUTION"),  # rule 1
    "CAPITAL_WITHDRAWAL": ("PARTNER_CAPITAL", False, "PARTNER_CAPITAL_WITHDRAWAL"),  # rule 2
    "DRAWING": ("PARTNER_CURRENT", False, "PARTNER_DRAWING"),  # rule 3
    "LOAN_TO_PARTNER": ("PARTNER_LOANS_RECEIVABLE", False, "PARTNER_LOAN"),  # rule 4
    "LOAN_TO_PARTNER_REPAYMENT": ("PARTNER_LOANS_RECEIVABLE", True, "PARTNER_LOAN_REPAYMENT"),  # rule 5
    "LOAN_FROM_PARTNER": ("PARTNER_LOANS_PAYABLE", True, "PARTNER_LOAN_TO_BUSINESS"),  # rule 28
    "LOAN_FROM_PARTNER_REPAYMENT": ("PARTNER_LOANS_PAYABLE", False, "PARTNER_LOAN_TO_BUSINESS_REPAYMENT"),  # rule 29
}


def partner_transaction(
    *,
    kind: PartnerTransactionKind,
    entry_date: date,
    amount: Decimal,
    partner_id: UUID,
    cash: CashAccountRef,
    description: str,
    source_id: UUID | None,
) -> EntryDraft:
    """Rules 1-5, 28, 29: money between the showroom's cash/bank and a partner.

    Money in  (1 contribution, 5 loan repayment, 28 partner lends): Dr cash / Cr partner account.
    Money out (2 withdrawal, 3 drawing, 4 loan to partner, 29 repay partner): Dr partner account / Cr cash.
    """
    amount = _positive_amount(amount)
    account_key, money_in, source_type = PARTNER_TRANSACTION_RULES[kind]
    cash_line = Line(
        account=cash.account,
        debit=amount if money_in else ZERO,
        credit=ZERO if money_in else amount,
        cash_account_id=cash.cash_account_id,
    )
    partner_line = Line(
        account=Account.system(account_key),
        debit=ZERO if money_in else amount,
        credit=amount if money_in else ZERO,
        partner_id=partner_id,
    )
    draft = EntryDraft(
        entry_date=entry_date,
        description=description,
        source_type=source_type,
        source_id=source_id,
        lines=(cash_line, partner_line) if money_in else (partner_line, cash_line),
    )
    draft.validate()
    return draft


def general_expense_paid_by_partner(
    *,
    entry_date: date,
    amount: Decimal,
    expense_account: Account,
    partner_id: UUID,
    mode: Literal["CURRENT_ACCOUNT", "LOAN"],
    description: str,
    source_id: UUID | None,
) -> EntryDraft:
    """Rule 30 — a partner pays an expense personally: Dr expense /
    Cr partner current account (mode CURRENT_ACCOUNT) or loans from partners (mode LOAN).
    The vehicle-cost variant (Dr vehicle inventory) arrives with vehicles in Phase 4."""
    amount = _positive_amount(amount)
    credit_key = "PARTNER_CURRENT" if mode == "CURRENT_ACCOUNT" else "PARTNER_LOANS_PAYABLE"
    draft = EntryDraft(
        entry_date=entry_date,
        description=description,
        source_type="GENERAL_EXPENSE",
        source_id=source_id,
        lines=(
            Line(account=expense_account, debit=amount),
            Line(account=Account.system(credit_key), credit=amount, partner_id=partner_id),
        ),
    )
    draft.validate()
    return draft


def other_income(
    *, entry_date: date, amount: Decimal, received_in: CashAccountRef, description: str, source_id: UUID | None
) -> EntryDraft:
    """P-01 (approved 2026-10-02) — other income: Dr cash/bank / Cr 4900 other income."""
    amount = _positive_amount(amount)
    draft = EntryDraft(
        entry_date=entry_date,
        description=description,
        source_type="OTHER_INCOME",
        source_id=source_id,
        lines=(
            Line(account=received_in.account, debit=amount, cash_account_id=received_in.cash_account_id),
            Line(account=Account.system("OTHER_INCOME"), credit=amount),
        ),
    )
    draft.validate()
    return draft
