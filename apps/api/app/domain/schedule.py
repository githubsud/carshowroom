"""Installment schedules (SPEC §4.8, BACKLOG 5.1).

Equal split rounded half-up to cents (A-07) with the rounding remainder on the
last installment (FACT), or a manual schedule that must add up exactly.
Pure functions; property-tested in tests/unit/test_installment_rules.py.
"""

import calendar
import itertools
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Literal

from app.domain.money import CENT, quantize

Frequency = Literal["MONTHLY", "BIWEEKLY", "WEEKLY", "QUARTERLY"]


class ScheduleError(ValueError):
    """The schedule cannot be built or does not add up."""


@dataclass(frozen=True)
class ScheduleRow:
    seq: int
    due_date: date
    amount: Decimal


def _add_months(start: date, months: int) -> date:
    """Same day of the month on a 30-day month, as for payroll (pilot review,
    D-90): a schedule starting on the 31st falls on the 30th after, and on
    February's last day (31 Jan -> 28 Feb -> 30 Mar -> 30 Apr)."""
    if months == 0:
        return start
    month_index = start.month - 1 + months
    year, month = start.year + month_index // 12, month_index % 12 + 1
    return date(year, month, min(start.day, 30, calendar.monthrange(year, month)[1]))


def due_dates(first: date, count: int, frequency: Frequency) -> list[date]:
    if frequency == "MONTHLY":
        return [_add_months(first, i) for i in range(count)]
    if frequency == "QUARTERLY":
        return [_add_months(first, 3 * i) for i in range(count)]
    step = timedelta(days=7 if frequency == "WEEKLY" else 14)
    return [first + step * i for i in range(count)]


def equal_schedule(financed: Decimal, count: int, first_due: date, frequency: Frequency) -> list[ScheduleRow]:
    if count < 1:
        raise ScheduleError("at least one installment")
    base = quantize(financed / count)
    last = financed - base * (count - 1)
    if base <= 0 or last <= 0 or financed != financed.quantize(CENT):
        raise ScheduleError("the amount is too small to split into this many installments")
    dates = due_dates(first_due, count, frequency)
    return [
        ScheduleRow(seq=i + 1, due_date=day, amount=last if i == count - 1 else base) for i, day in enumerate(dates)
    ]


def validate_manual(financed: Decimal, rows: list[ScheduleRow]) -> None:
    if not rows:
        raise ScheduleError("at least one installment")
    if any(row.amount <= 0 or row.amount != row.amount.quantize(CENT) for row in rows):
        raise ScheduleError("every installment is a positive amount with at most 2 decimals")
    if any(later.due_date < earlier.due_date for earlier, later in itertools.pairwise(rows)):
        raise ScheduleError("due dates must run forward")
    total = sum((row.amount for row in rows), Decimal(0))
    if total != financed:
        raise ScheduleError(f"the installments total {total}, not {financed}")
