"""Posting rules 1-5, 28, 29, 30 and P-01 (docs/ACCOUNTING.md §3, §5), written
before the endpoints. Amounts follow the ACCOUNTING.md worked examples."""

import uuid
from datetime import date
from decimal import Decimal

import pytest

from app.domain.ledger import Account, CashAccountRef, LedgerRuleError, Line
from app.services.posting import rules

D = date(2026, 10, 2)
AHMED = uuid.uuid4()
CASH = CashAccountRef(cash_account_id=uuid.uuid4(), ledger_account_id=uuid.uuid4())
RENT = Account.by_id(uuid.uuid4())


def cash_line(debit: str = "0", credit: str = "0") -> Line:
    return Line(
        account=CASH.account, debit=Decimal(debit), credit=Decimal(credit), cash_account_id=CASH.cash_account_id
    )


def partner_line(key: str, debit: str = "0", credit: str = "0") -> Line:
    return Line(account=Account.system(key), debit=Decimal(debit), credit=Decimal(credit), partner_id=AHMED)


@pytest.mark.parametrize(
    ("kind", "amount", "expected_lines", "source_type"),
    [
        # Rule 1: Dr cash / Cr partner capital
        (
            "CONTRIBUTION",
            "1000000.00",
            [cash_line(debit="1000000.00"), partner_line("PARTNER_CAPITAL", credit="1000000.00")],
            "PARTNER_CONTRIBUTION",
        ),
        # Rule 2: Dr partner capital / Cr cash
        (
            "CAPITAL_WITHDRAWAL",
            "100000.00",
            [partner_line("PARTNER_CAPITAL", debit="100000.00"), cash_line(credit="100000.00")],
            "PARTNER_CAPITAL_WITHDRAWAL",
        ),
        # Rule 3: Dr partner current account / Cr cash
        (
            "DRAWING",
            "50000.00",
            [partner_line("PARTNER_CURRENT", debit="50000.00"), cash_line(credit="50000.00")],
            "PARTNER_DRAWING",
        ),
        # Rule 4: Dr loans to partners / Cr cash
        (
            "LOAN_TO_PARTNER",
            "30000.00",
            [partner_line("PARTNER_LOANS_RECEIVABLE", debit="30000.00"), cash_line(credit="30000.00")],
            "PARTNER_LOAN",
        ),
        # Rule 5: Dr cash / Cr loans to partners
        (
            "LOAN_TO_PARTNER_REPAYMENT",
            "10000.00",
            [cash_line(debit="10000.00"), partner_line("PARTNER_LOANS_RECEIVABLE", credit="10000.00")],
            "PARTNER_LOAN_REPAYMENT",
        ),
        # Rule 28: Dr cash / Cr loans from partners
        (
            "LOAN_FROM_PARTNER",
            "100000.00",
            [cash_line(debit="100000.00"), partner_line("PARTNER_LOANS_PAYABLE", credit="100000.00")],
            "PARTNER_LOAN_TO_BUSINESS",
        ),
        # Rule 29: Dr loans from partners / Cr cash
        (
            "LOAN_FROM_PARTNER_REPAYMENT",
            "40000.00",
            [partner_line("PARTNER_LOANS_PAYABLE", debit="40000.00"), cash_line(credit="40000.00")],
            "PARTNER_LOAN_TO_BUSINESS_REPAYMENT",
        ),
    ],
)
def test_partner_transaction_rules(kind: str, amount: str, expected_lines: list[Line], source_type: str) -> None:
    source = uuid.uuid4()
    draft = rules.partner_transaction(
        kind=kind,  # type: ignore[arg-type]
        entry_date=D,
        amount=Decimal(amount),
        partner_id=AHMED,
        cash=CASH,
        description="x",
        source_id=source,
    )
    assert list(draft.lines) == expected_lines
    assert draft.source_type == source_type
    assert draft.source_id == source
    debit = sum((line.debit for line in draft.lines), Decimal(0))
    assert debit == sum((line.credit for line in draft.lines), Decimal(0)) == Decimal(amount)


def test_every_partner_line_carries_the_partner() -> None:
    for kind in rules.PARTNER_TRANSACTION_RULES:
        draft = rules.partner_transaction(
            kind=kind,
            entry_date=D,
            amount=Decimal("1.00"),
            partner_id=AHMED,
            cash=CASH,
            description="x",
            source_id=None,
        )
        partner_lines = [line for line in draft.lines if line.cash_account_id is None]
        assert [line.partner_id for line in partner_lines] == [AHMED]


def test_partner_transaction_rejects_bad_amounts() -> None:
    with pytest.raises(LedgerRuleError):
        rules.partner_transaction(
            kind="DRAWING",
            entry_date=D,
            amount=Decimal("0"),
            partner_id=AHMED,
            cash=CASH,
            description="x",
            source_id=None,
        )


@pytest.mark.parametrize(
    ("mode", "credit_key"), [("CURRENT_ACCOUNT", "PARTNER_CURRENT"), ("LOAN", "PARTNER_LOANS_PAYABLE")]
)
def test_rule_30_expense_paid_personally_by_a_partner(mode: str, credit_key: str) -> None:
    """ACCOUNTING.md rule 30: Ahmed pays 3,000 personally; credited to his current account or as a loan."""
    draft = rules.general_expense_paid_by_partner(
        entry_date=D,
        amount=Decimal("3000.00"),
        expense_account=RENT,
        partner_id=AHMED,
        mode=mode,  # type: ignore[arg-type]
        description="x",
        source_id=None,
    )
    assert draft.source_type == "GENERAL_EXPENSE"
    assert list(draft.lines) == [
        Line(account=RENT, debit=Decimal("3000.00")),
        Line(account=Account.system(credit_key), credit=Decimal("3000.00"), partner_id=AHMED),
    ]
    assert draft.cash_effects() == {}  # no cash moves


def test_p01_other_income() -> None:
    """P-01 (approved): Dr cash/bank / Cr 4900 other income."""
    draft = rules.other_income(
        entry_date=D, amount=Decimal("20000.00"), received_in=CASH, description="x", source_id=None
    )
    assert draft.source_type == "OTHER_INCOME"
    assert list(draft.lines) == [
        cash_line(debit="20000.00"),
        Line(account=Account.system("OTHER_INCOME"), credit=Decimal("20000.00")),
    ]
