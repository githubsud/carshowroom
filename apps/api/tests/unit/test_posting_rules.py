"""Posting rules 20, 21 and 24 (docs/ACCOUNTING.md §3), written before the endpoints.

Each rule must: balance, hit the right accounts, carry the right subledger ids,
use the exact amounts, and refuse invalid input.
"""

import uuid
from datetime import date
from decimal import Decimal

import pytest

from app.domain.ledger import Account, CashAccountRef, EntryDraft, LedgerRuleError, Line
from app.services.posting import rules

D = date(2026, 10, 2)
RENT = Account.by_id(uuid.uuid4())
MAIN_CASH = CashAccountRef(cash_account_id=uuid.uuid4(), ledger_account_id=uuid.uuid4())
CIB = CashAccountRef(cash_account_id=uuid.uuid4(), ledger_account_id=uuid.uuid4())


def _totals(draft: EntryDraft) -> tuple[Decimal, Decimal]:
    return sum((line.debit for line in draft.lines), Decimal(0)), sum((line.credit for line in draft.lines), Decimal(0))


# --- Rule 20: general expense ------------------------------------------------------


def test_rule_20_general_expense_debits_expense_and_credits_cash() -> None:
    """ACCOUNTING.md rule 20: monthly rent 25,000 paid from CIB."""
    source = uuid.uuid4()
    draft = rules.general_expense(
        entry_date=D,
        amount=Decimal("25000.00"),
        expense_account=RENT,
        paid_from=CIB,
        description="إيجار أكتوبر",
        source_id=source,
    )
    assert draft.source_type == "GENERAL_EXPENSE"
    assert draft.source_id == source
    assert draft.entry_date == D
    assert _totals(draft) == (Decimal("25000.00"), Decimal("25000.00"))

    debit, credit = draft.lines
    assert debit == Line(account=RENT, debit=Decimal("25000.00"))
    assert credit == Line(
        account=Account.by_id(CIB.ledger_account_id),
        credit=Decimal("25000.00"),
        cash_account_id=CIB.cash_account_id,
    )


@pytest.mark.parametrize("amount", ["0", "-1.00", "10.005"])
def test_rule_20_rejects_non_positive_or_imprecise_amounts(amount: str) -> None:
    with pytest.raises(LedgerRuleError):
        rules.general_expense(
            entry_date=D,
            amount=Decimal(amount),
            expense_account=RENT,
            paid_from=CIB,
            description="x",
            source_id=None,
        )


# --- Rule 21: cash <-> bank transfer ----------------------------------------------------


def test_rule_21_transfer_debits_destination_and_credits_source() -> None:
    """ACCOUNTING.md rule 21: deposit 100,000 cash into CIB."""
    draft = rules.transfer(
        entry_date=D,
        amount=Decimal("100000.00"),
        source=MAIN_CASH,
        destination=CIB,
        description="إيداع",
        source_id=None,
    )
    assert draft.source_type == "TRANSFER"
    assert _totals(draft) == (Decimal("100000.00"), Decimal("100000.00"))
    debit, credit = draft.lines
    assert debit.account == Account.by_id(CIB.ledger_account_id)
    assert debit.cash_account_id == CIB.cash_account_id
    assert debit.debit == Decimal("100000.00")
    assert credit.account == Account.by_id(MAIN_CASH.ledger_account_id)
    assert credit.cash_account_id == MAIN_CASH.cash_account_id
    assert credit.credit == Decimal("100000.00")


def test_rule_21_rejects_transfer_to_the_same_account() -> None:
    with pytest.raises(LedgerRuleError, match="same"):
        rules.transfer(
            entry_date=D, amount=Decimal("5.00"), source=CIB, destination=CIB, description="x", source_id=None
        )


# --- Rule 24: reversal ----------------------------------------------------------------


def test_rule_24_reversal_mirrors_every_line_with_its_subledgers() -> None:
    partner = uuid.uuid4()
    original = (
        Line(account=RENT, debit=Decimal("300.00")),
        Line(account=Account.by_id(uuid.uuid4()), debit=Decimal("200.00"), partner_id=partner, memo="m"),
        Line(
            account=Account.by_id(CIB.ledger_account_id),
            credit=Decimal("500.00"),
            cash_account_id=CIB.cash_account_id,
        ),
    )
    mirror = rules.reversal_lines(original)
    assert [(line.debit, line.credit) for line in mirror] == [
        (Decimal("0"), Decimal("300.00")),
        (Decimal("0"), Decimal("200.00")),
        (Decimal("500.00"), Decimal("0")),
    ]
    assert mirror[1].partner_id == partner
    assert mirror[1].memo == "m"
    assert mirror[2].cash_account_id == CIB.cash_account_id
    # Original + reversal leave every account where it was.
    net: dict[object, Decimal] = {}
    for line in (*original, *mirror):
        net[line.account] = net.get(line.account, Decimal(0)) + line.debit - line.credit
    assert set(net.values()) == {Decimal(0)}


def test_cash_effects_report_the_change_per_cash_account() -> None:
    draft = rules.transfer(
        entry_date=D,
        amount=Decimal("70.00"),
        source=MAIN_CASH,
        destination=CIB,
        description="x",
        source_id=None,
    )
    assert draft.cash_effects() == {
        MAIN_CASH.cash_account_id: Decimal("-70.00"),
        CIB.cash_account_id: Decimal("70.00"),
    }


# --- Draft validation (mirrors the database rules) -------------------------------------


def test_draft_rejects_unbalanced_entries() -> None:
    with pytest.raises(LedgerRuleError, match="balance"):
        EntryDraft(
            entry_date=D,
            description="x",
            source_type="TEST",
            source_id=None,
            lines=(Line(account=RENT, debit=Decimal("10.00")), Line(account=RENT, credit=Decimal("9.00"))),
        ).validate()


def test_draft_rejects_single_line_and_two_sided_lines() -> None:
    with pytest.raises(LedgerRuleError):
        EntryDraft(
            entry_date=D,
            description="x",
            source_type="TEST",
            source_id=None,
            lines=(Line(account=RENT, debit=Decimal("1.00")),),
        ).validate()
    with pytest.raises(LedgerRuleError):
        Line(account=RENT, debit=Decimal("1.00"), credit=Decimal("1.00")).validate()


def test_draft_payload_for_the_database() -> None:
    draft = rules.general_expense(
        entry_date=D,
        amount=Decimal("12.50"),
        expense_account=RENT,
        paid_from=CIB,
        description="x",
        source_id=None,
    )
    payload = draft.to_payload({})
    assert payload["entry_date"] == "2026-10-02"
    assert payload["lines"][0] == {
        "ledger_account_id": str(RENT.ledger_account_id),
        "debit": "12.50",
        "credit": "0.00",
    }
    assert payload["lines"][1]["cash_account_id"] == str(CIB.cash_account_id)


def test_system_accounts_are_resolved_by_key() -> None:
    other_income = Account.system("OTHER_INCOME")
    resolved = uuid.uuid4()
    draft = EntryDraft(
        entry_date=D,
        description="x",
        source_type="TEST",
        source_id=None,
        lines=(Line(account=other_income, credit=Decimal("5.00")), Line(account=RENT, debit=Decimal("5.00"))),
    )
    assert draft.to_payload({"OTHER_INCOME": resolved})["lines"][0]["ledger_account_id"] == str(resolved)
    with pytest.raises(LedgerRuleError, match="OTHER_INCOME"):
        draft.to_payload({})
