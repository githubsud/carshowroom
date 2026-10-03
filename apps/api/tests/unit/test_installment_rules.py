"""Phase 5: the installment schedule (SPEC §4.8) and rules 13, 15, 27, the
P-02 credit legs and P-07 bank charges. Written before the services."""

import random
import uuid
from datetime import date
from decimal import Decimal

import pytest

from app.domain.ledger import Account, CashAccountRef, LedgerRuleError, Line
from app.domain.schedule import ScheduleError, ScheduleRow, due_dates, equal_schedule, validate_manual
from app.services.posting import rules

D = date(2026, 10, 2)
V2 = uuid.uuid4()
MARIAM = uuid.uuid4()
CASH = CashAccountRef(cash_account_id=uuid.uuid4(), ledger_account_id=uuid.uuid4())
BANK = CashAccountRef(cash_account_id=uuid.uuid4(), ledger_account_id=uuid.uuid4())


def money(value: str) -> Decimal:
    return Decimal(value)


def system(key: str, debit: str = "0", credit: str = "0", **ids: uuid.UUID) -> Line:
    return Line(account=Account.system(key), debit=money(debit), credit=money(credit), **ids)


def cash(ref: CashAccountRef, debit: str = "0", credit: str = "0") -> Line:
    return Line(account=ref.account, debit=money(debit), credit=money(credit), cash_account_id=ref.cash_account_id)


# --- Schedule -------------------------------------------------------------------------------------


def test_accounting_example_puts_the_remainder_on_the_last_installment() -> None:
    # ACCOUNTING.md rule 13: 450,000 in 7 -> 6 x 64,285.71 and a last one of 64,285.74.
    rows = equal_schedule(money("450000.00"), 7, date(2026, 11, 1), "MONTHLY")
    assert [row.amount for row in rows[:6]] == [money("64285.71")] * 6
    assert rows[-1].amount == money("64285.74")
    assert sum(row.amount for row in rows) == money("450000.00")
    assert [row.seq for row in rows] == list(range(1, 8))


def test_monthly_dates_keep_the_day_on_a_30_day_month() -> None:
    # Pilot review (D-90): like payroll, the 31st becomes the 30th; February takes its last day.
    assert due_dates(date(2026, 1, 31), 5, "MONTHLY") == [
        date(2026, 1, 31),
        date(2026, 2, 28),
        date(2026, 3, 30),
        date(2026, 4, 30),
        date(2026, 5, 30),
    ]
    assert due_dates(date(2027, 12, 30), 3, "MONTHLY") == [date(2027, 12, 30), date(2028, 1, 30), date(2028, 2, 29)]
    assert due_dates(date(2026, 1, 15), 3, "MONTHLY") == [date(2026, 1, 15), date(2026, 2, 15), date(2026, 3, 15)]
    assert due_dates(date(2026, 5, 31), 2, "QUARTERLY") == [date(2026, 5, 31), date(2026, 8, 30)]
    assert due_dates(date(2026, 1, 5), 3, "QUARTERLY") == [date(2026, 1, 5), date(2026, 4, 5), date(2026, 7, 5)]
    assert due_dates(date(2026, 1, 5), 3, "WEEKLY") == [date(2026, 1, 5), date(2026, 1, 12), date(2026, 1, 19)]
    assert due_dates(date(2026, 1, 5), 2, "BIWEEKLY") == [date(2026, 1, 5), date(2026, 1, 19)]


def test_property_any_split_adds_up_exactly() -> None:
    """Property test (BACKLOG 5.1): for many random amounts and counts, the
    installments total the financed amount, all but the last are equal, and
    none is zero or negative."""
    generator = random.Random(20261002)  # noqa: S311 - reproducible test data, not security
    for _ in range(2000):
        count = generator.randint(1, 120)
        cents = generator.randint(count, 10**12)
        financed = Decimal(cents) / 100
        rows = equal_schedule(financed, count, D, generator.choice(["MONTHLY", "WEEKLY", "BIWEEKLY", "QUARTERLY"]))
        assert len(rows) == count
        assert sum(row.amount for row in rows) == financed
        assert len({row.amount for row in rows[:-1]}) <= 1
        assert all(row.amount > 0 for row in rows)
        assert [row.due_date for row in rows] == sorted(row.due_date for row in rows)


def test_too_small_to_split_is_refused() -> None:
    with pytest.raises(ScheduleError):
        equal_schedule(money("0.03"), 4, D, "MONTHLY")
    with pytest.raises(ScheduleError):
        equal_schedule(money("100"), 0, D, "MONTHLY")


def test_manual_schedule_must_add_up_and_run_forward() -> None:
    good = [ScheduleRow(1, date(2026, 11, 1), money("600")), ScheduleRow(2, date(2026, 12, 1), money("400"))]
    validate_manual(money("1000"), good)
    with pytest.raises(ScheduleError):
        validate_manual(money("1000.01"), good)
    with pytest.raises(ScheduleError):
        validate_manual(money("1000"), list(reversed(good)))
    with pytest.raises(ScheduleError):
        validate_manual(money("0"), [ScheduleRow(1, D, money("0"))])


# --- Rule 13: installment sale (mode a) ------------------------------------------------------------


def test_rule_13_down_payment_and_receivable() -> None:
    draft = rules.sale(
        entry_date=D,
        vehicle_id=V2,
        buyer_id=MARIAM,
        sale_price=money("600000.00"),
        payments=[(CASH, money("150000.00"))],
        deposit_applied=money("0"),
        trade_in=None,
        financed=money("450000.00"),
        description="بيع بالتقسيط",
        source_id=None,
    )
    assert draft.lines == (
        cash(CASH, debit="150000.00"),
        system("INSTALLMENT_RECEIVABLE", debit="450000.00", customer_id=MARIAM),
        system("VEHICLE_SALES", credit="600000.00", vehicle_id=V2),
    )


# --- Rule 15: installment collected; P-02 credit legs ----------------------------------------------------


def test_rule_15_collection_into_cash() -> None:
    draft = rules.installment_receipt(
        entry_date=D,
        customer_id=MARIAM,
        allocated=money("75000.00"),
        received_in=CASH,
        excess_to_credit=money("0"),
        description="قسط",
        source_id=None,
    )
    assert draft.source_type == "INSTALLMENT_RECEIPT"
    assert draft.lines == (
        cash(CASH, debit="75000.00"),
        system("INSTALLMENT_RECEIVABLE", credit="75000.00", customer_id=MARIAM),
    )


def test_p02_overpayment_kept_as_customer_credit() -> None:
    draft = rules.installment_receipt(
        entry_date=D,
        customer_id=MARIAM,
        allocated=money("75000.00"),
        received_in=BANK,
        excess_to_credit=money("5000.00"),
        description="قسط",
        source_id=None,
    )
    assert draft.lines == (
        cash(BANK, debit="80000.00"),
        system("INSTALLMENT_RECEIVABLE", credit="75000.00", customer_id=MARIAM),
        system("CUSTOMER_CREDITS", credit="5000.00", customer_id=MARIAM),
    )


def test_p02_customer_credit_applied_to_an_installment() -> None:
    draft = rules.installment_receipt(
        entry_date=D,
        customer_id=MARIAM,
        allocated=money("5000.00"),
        received_in=None,
        excess_to_credit=money("0"),
        description="خصم من الرصيد",
        source_id=None,
    )
    assert draft.lines == (
        system("CUSTOMER_CREDITS", debit="5000.00", customer_id=MARIAM),
        system("INSTALLMENT_RECEIVABLE", credit="5000.00", customer_id=MARIAM),
    )
    assert draft.cash_effects() == {}


def test_credit_cannot_create_more_credit() -> None:
    with pytest.raises(LedgerRuleError):
        rules.installment_receipt(
            entry_date=D,
            customer_id=MARIAM,
            allocated=money("1"),
            received_in=None,
            excess_to_credit=money("1"),
            description="x",
            source_id=None,
        )


# --- Rule 27 and P-07 -------------------------------------------------------------------------------------


def test_rule_27_bounced_cheque_restores_the_receivable() -> None:
    draft = rules.cheque_bounced(
        entry_date=D, customer_id=MARIAM, amount=money("75000.00"), bank=BANK, description="شيك مرتد", source_id=None
    )
    assert draft.source_type == "CHEQUE_BOUNCE"
    assert draft.lines == (
        system("INSTALLMENT_RECEIVABLE", debit="75000.00", customer_id=MARIAM),
        cash(BANK, credit="75000.00"),
    )


def test_p07_bank_charges_to_expense_or_to_the_customer() -> None:
    expense = rules.bounce_charges(
        entry_date=D, amount=money("150.00"), bank=BANK, charge_customer_id=None, description="x", source_id=None
    )
    assert expense.lines == (system("EXP_BANK_CHARGES", debit="150.00"), cash(BANK, credit="150.00"))
    recharged = rules.bounce_charges(
        entry_date=D, amount=money("150.00"), bank=BANK, charge_customer_id=MARIAM, description="x", source_id=None
    )
    assert recharged.lines == (
        system("OTHER_RECEIVABLE", debit="150.00", customer_id=MARIAM),
        cash(BANK, credit="150.00"),
    )


# --- P-03 with installments outstanding ----------------------------------------------------------------------


def test_p03_cancellation_releases_the_outstanding_receivable() -> None:
    """600,000 sale: 150,000 down, 450,000 financed of which 150,000 collected.
    Cancelling owes the customer 300,000 and clears the 300,000 still receivable."""
    draft = rules.sale_cancellation_to_credit(
        entry_date=D,
        vehicle_id=V2,
        buyer_id=MARIAM,
        sale_price=money("600000.00"),
        amount_paid=money("300000.00"),
        trade_in=None,
        receivable_outstanding=money("300000.00"),
        description="إلغاء",
        source_id=None,
    )
    assert draft.lines == (
        system("VEHICLE_SALES", debit="600000.00", vehicle_id=V2),
        system("CUSTOMER_CREDITS", credit="300000.00", customer_id=MARIAM),
        system("INSTALLMENT_RECEIVABLE", credit="300000.00", customer_id=MARIAM),
    )
