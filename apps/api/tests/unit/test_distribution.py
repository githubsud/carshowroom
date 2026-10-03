"""Profit distribution arithmetic (rule 22, D-40): ownership segments,
day-weighted and sub-period pro-rata, and the rounding-remainder rules.
Expected values follow docs/ACCOUNTING.md §3 (rule 22) and §4."""

import uuid
from datetime import date
from decimal import Decimal

import pytest

from app.domain.distribution import (
    DistributionError,
    ShareRow,
    allocate,
    day_weights,
    round_shares,
    segments,
    sub_period_shares,
)
from app.domain.ledger import Account, Line
from app.services.posting import rules

A, B, C = (uuid.UUID(f"00000000-0000-0000-0000-00000000000{i}") for i in (1, 2, 3))
JAN1, JAN15, JAN16, JAN31 = date(2026, 1, 1), date(2026, 1, 15), date(2026, 1, 16), date(2026, 1, 31)


def money(value: str) -> Decimal:
    return Decimal(value)


def test_scenario_split_50_30_20() -> None:
    weights = {A: Decimal(50), B: Decimal(30), C: Decimal(20)}
    assert allocate(money("235000.00"), weights, "LARGEST_REMAINDER") == {
        A: money("117500.00"),
        B: money("70500.00"),
        C: money("47000.00"),
    }


def test_a_loss_is_allocated_with_the_same_weights() -> None:
    weights = {A: Decimal(50), B: Decimal(30), C: Decimal(20)}
    assert allocate(money("-100.00"), weights, "LARGEST_REMAINDER") == {
        A: money("-50.00"),
        B: money("-30.00"),
        C: money("-20.00"),
    }


def test_day_weighted_example_from_accounting() -> None:
    history = [
        ShareRow(A, Decimal(50), JAN1, JAN15),
        ShareRow(A, Decimal(40), JAN16, None),
        ShareRow(B, Decimal(30), JAN1, JAN15),
        ShareRow(B, Decimal(40), JAN16, None),
        ShareRow(C, Decimal(20), JAN1, None),
    ]
    weights = day_weights(segments(history, JAN1, JAN31))
    assert sum(weights.values()) == Decimal(100)
    assert allocate(money("100000.00"), weights, "LARGEST_REMAINDER") == {
        A: money("44838.71"),
        B: money("35161.29"),
        C: money("20000.00"),
    }


def test_largest_remainder_gives_the_cent_to_the_largest_fraction() -> None:
    exact = {A: Decimal("33.334"), B: Decimal("33.333"), C: Decimal("33.333")}
    weights = {A: Decimal("33.3334"), B: Decimal("33.3333"), C: Decimal("33.3333")}
    assert round_shares(exact, money("100.00"), weights, "LARGEST_REMAINDER") == {
        A: money("33.34"),
        B: money("33.33"),
        C: money("33.33"),
    }


def test_largest_share_gives_every_remaining_cent_to_the_largest_partner() -> None:
    weights = {A: Decimal(25), B: Decimal("37.5"), C: Decimal("37.5")}
    third = allocate(money("0.10"), {A: Decimal(1), B: Decimal(1), C: Decimal(1)}, "LARGEST_SHARE")
    assert sum(third.values()) == money("0.10")
    result = allocate(money("100.01"), weights, "LARGEST_SHARE")
    assert sum(result.values()) == money("100.01")
    # 25.0025 / 37.50375 / 37.50375 -> floors 25.00 / 37.50 / 37.50, one cent left, to B (first of the largest).
    assert result == {A: money("25.00"), B: money("37.51"), C: money("37.50")}


def test_allocation_always_adds_up_exactly() -> None:
    weights = {A: Decimal("33.3334"), B: Decimal("33.3333"), C: Decimal("33.3333")}
    for cents in (1, 2, 99, 100, 101, 12345, 99999):
        amount = Decimal(cents) / 100
        for method in ("LARGEST_REMAINDER", "LARGEST_SHARE"):
            assert sum(allocate(amount, weights, method).values()) == amount  # type: ignore[arg-type]
            assert sum(allocate(-amount, weights, method).values()) == -amount  # type: ignore[arg-type]


def test_segments_need_shares_on_every_day() -> None:
    history = [ShareRow(A, Decimal(100), JAN16, None)]
    with pytest.raises(DistributionError) as error:
        segments(history, JAN1, JAN31)
    assert error.value.code == "DISTRIBUTION_SHARES_MISSING"


def test_sub_period_profit_uses_each_segments_own_profit() -> None:
    """Profit 100,000 earned entirely in days 16-31: only the shares of that sub-period count."""
    history = [
        ShareRow(A, Decimal(50), JAN1, JAN15),
        ShareRow(A, Decimal(40), JAN16, None),
        ShareRow(B, Decimal(50), JAN1, JAN15),
        ShareRow(B, Decimal(60), JAN16, None),
    ]
    parts = segments(history, JAN1, JAN31)
    assert [(s.start, s.end) for s in parts] == [(JAN1, JAN15), (JAN16, JAN31)]
    exact = sub_period_shares(parts, [money("0"), money("100000.00")])
    assert round_shares(exact, money("100000.00"), day_weights(parts), "LARGEST_REMAINDER") == {
        A: money("40000.00"),
        B: money("60000.00"),
    }


# --- Rules 22 and 23 -----------------------------------------------------------------------------------

V1 = uuid.uuid4()
SALES = Account.by_id(uuid.uuid4())
COGS = Account.by_id(uuid.uuid4())
RENT = Account.by_id(uuid.uuid4())


def test_rule_23_closes_income_and_expenses_into_retained_earnings() -> None:
    balances = (
        Line(account=SALES, credit=money("480000.00"), vehicle_id=V1),
        Line(account=COGS, debit=money("415000.00"), vehicle_id=V1),
        Line(account=RENT, debit=money("25000.00")),
    )
    draft = rules.period_close(entry_date=JAN31, balances=balances, description="إقفال", source_id=None)
    assert draft.is_closing
    assert draft.source_type == "PERIOD_CLOSE"
    assert draft.lines == (
        Line(account=SALES, debit=money("480000.00"), vehicle_id=V1),
        Line(account=COGS, credit=money("415000.00"), vehicle_id=V1),
        Line(account=RENT, credit=money("25000.00")),
        Line(account=Account.system("RETAINED_EARNINGS"), credit=money("40000.00")),
    )


def test_rule_23_a_loss_debits_retained_earnings() -> None:
    balances = (Line(account=RENT, debit=money("25000.00")),)
    draft = rules.period_close(entry_date=JAN31, balances=balances, description="إقفال", source_id=None)
    assert draft.lines[-1] == Line(account=Account.system("RETAINED_EARNINGS"), debit=money("25000.00"))


def test_rule_22_credits_each_partner_current_account() -> None:
    draft = rules.profit_distribution(
        entry_date=JAN31,
        shares=[(A, money("27500.00")), (B, money("16500.00")), (C, money("11000.00"))],
        description="توزيع",
        source_id=None,
    )
    assert draft.is_closing
    assert draft.lines == (
        Line(account=Account.system("RETAINED_EARNINGS"), debit=money("55000.00")),
        Line(account=Account.system("PARTNER_CURRENT"), credit=money("27500.00"), partner_id=A),
        Line(account=Account.system("PARTNER_CURRENT"), credit=money("16500.00"), partner_id=B),
        Line(account=Account.system("PARTNER_CURRENT"), credit=money("11000.00"), partner_id=C),
    )


def test_p09_a_loss_is_charged_to_partner_current_accounts() -> None:
    draft = rules.profit_distribution(
        entry_date=JAN31, shares=[(A, money("-60.00")), (B, money("-40.00"))], description="خسارة", source_id=None
    )
    assert draft.lines == (
        Line(account=Account.system("PARTNER_CURRENT"), debit=money("60.00"), partner_id=A),
        Line(account=Account.system("PARTNER_CURRENT"), debit=money("40.00"), partner_id=B),
        Line(account=Account.system("RETAINED_EARNINGS"), credit=money("100.00")),
    )


def test_p10_per_car_allocation_in_advance_and_netting() -> None:
    allocation = rules.profit_allocation(
        entry_date=JAN15,
        shares=[(A, money("35000.00")), (B, money("35000.00"))],
        description="ربح سيارة",
        source_id=None,
    )
    assert not allocation.is_closing
    assert allocation.lines == (
        Line(account=Account.system("PROFIT_ALLOCATED_IN_ADVANCE"), debit=money("70000.00")),
        Line(account=Account.system("PARTNER_CURRENT"), credit=money("35000.00"), partner_id=A),
        Line(account=Account.system("PARTNER_CURRENT"), credit=money("35000.00"), partner_id=B),
    )
    netting = rules.advance_netting(entry_date=JAN31, amount=money("70000.00"), description="مقاصة", source_id=None)
    assert netting.is_closing
    assert netting.lines == (
        Line(account=Account.system("RETAINED_EARNINGS"), debit=money("70000.00")),
        Line(account=Account.system("PROFIT_ALLOCATED_IN_ADVANCE"), credit=money("70000.00")),
    )
