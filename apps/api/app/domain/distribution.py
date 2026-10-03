"""Profit distribution (SPEC §4.9, rules 22 and 23, D-40).

Pure arithmetic, unit-tested in tests/unit/test_distribution.py:

* ``segments``: the period cut into stretches where every partner's share is
  constant; shares must total 100 on every day (D-21 guarantees it per date).
* ``day_weights``: DAY_WEIGHTED pro-rata — each partner's % weighted by days.
* ``sub_period_shares``: SUB_PERIOD_PROFIT — each stretch's own profit split by
  the shares in force in it.
* ``round_shares`` / ``allocate``: cents that add up exactly, the remainder by
  LARGEST_REMAINDER (largest fractional part) or LARGEST_SHARE (largest %).
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import ROUND_DOWN, Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel

from app.domain.money import CENT, Money
from app.domain.vehicles import NoteText, ReasonText, StrictModel

RoundingMethod = Literal["LARGEST_REMAINDER", "LARGEST_SHARE"]
ProrataMethod = Literal["DAY_WEIGHTED", "SUB_PERIOD_PROFIT"]
_HUNDRED = Decimal(100)
_ZERO = Decimal(0)


class DistributionError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class ShareRow:
    partner_id: UUID
    percentage: Decimal
    effective_from: date
    effective_to: date | None


@dataclass(frozen=True)
class Segment:
    start: date
    end: date
    shares: dict[UUID, Decimal]

    @property
    def days(self) -> int:
        return (self.end - self.start).days + 1


def _shares_on(history: Sequence[ShareRow], day: date) -> dict[UUID, Decimal]:
    return {
        row.partner_id: row.percentage
        for row in history
        if row.effective_from <= day and (row.effective_to is None or day <= row.effective_to)
    }


def segments(history: Sequence[ShareRow], period_from: date, period_to: date) -> list[Segment]:
    """Stretches of constant ownership covering the whole period."""
    if period_to < period_from:
        raise DistributionError("DATE_RANGE_INVALID", "the period ends before it starts")
    cuts = {period_from}
    for row in history:
        if period_from < row.effective_from <= period_to:
            cuts.add(row.effective_from)
        if row.effective_to is not None and period_from <= row.effective_to < period_to:
            cuts.add(row.effective_to + timedelta(days=1))
    starts = sorted(cuts)
    result = []
    for index, start in enumerate(starts):
        end = starts[index + 1] - timedelta(days=1) if index + 1 < len(starts) else period_to
        shares = _shares_on(history, start)
        if sum(shares.values(), _ZERO) != _HUNDRED:
            raise DistributionError(
                "DISTRIBUTION_SHARES_MISSING", f"partner shares do not total 100% on {start.isoformat()}"
            )
        result.append(Segment(start, end, shares))
    return result


def day_weights(parts: Sequence[Segment]) -> dict[UUID, Decimal]:
    """Each partner's % weighted by the days it was held (exact, totals 100)."""
    total_days = sum(part.days for part in parts)
    weights: dict[UUID, Decimal] = {}
    for part in parts:
        for partner, pct in part.shares.items():
            weights[partner] = weights.get(partner, _ZERO) + pct * part.days
    return {partner: value / total_days for partner, value in weights.items()}


def sub_period_shares(parts: Sequence[Segment], amounts: Sequence[Decimal]) -> dict[UUID, Decimal]:
    """Exact (unrounded) shares when each stretch's own amount is split by its own %."""
    exact: dict[UUID, Decimal] = {}
    for part, amount in zip(parts, amounts, strict=True):
        for partner, pct in part.shares.items():
            exact[partner] = exact.get(partner, _ZERO) + amount * pct / _HUNDRED
    return exact


def round_shares[K](
    exact: dict[K, Decimal], total: Decimal, weights: dict[K, Decimal], method: RoundingMethod
) -> dict[K, Decimal]:
    """Round exact shares to cents so they add up to `total` exactly (Q-18, D-40)."""
    if total != total.quantize(CENT):
        raise DistributionError("INVALID_AMOUNT", "the total has more than 2 decimals")
    sign = Decimal(-1) if total < 0 else Decimal(1)
    magnitudes = {key: value * sign for key, value in exact.items()}
    floors = {key: value.quantize(CENT, rounding=ROUND_DOWN) for key, value in magnitudes.items()}
    left = int(((total * sign) - sum(floors.values(), _ZERO)) / CENT)
    # Deterministic order; ties go to the larger weight, then the key's text order.
    order = sorted(floors, key=lambda key: str(key))
    if method == "LARGEST_REMAINDER":
        ranked = sorted(order, key=lambda key: (magnitudes[key] - floors[key], weights.get(key, _ZERO)), reverse=True)
        receivers = [ranked[i % len(ranked)] for i in range(max(left, 0))]
    else:
        largest = max(order, key=lambda key: weights.get(key, _ZERO))
        receivers = [largest] * max(left, 0)
    for key in receivers:
        floors[key] += CENT
    return {key: value * sign for key, value in floors.items()}


def allocate[K](amount: Decimal, weights: dict[K, Decimal], method: RoundingMethod) -> dict[K, Decimal]:
    """Split `amount` by percentage weights (summing to 100, or any positive scale)."""
    scale = sum(weights.values(), _ZERO)
    if scale <= 0:
        raise DistributionError("DISTRIBUTION_SHARES_MISSING", "no partner shares")
    exact = {key: amount * weight / scale for key, weight in weights.items()}
    return round_shares(exact, amount, weights, method)


# --- API models ------------------------------------------------------------------------------------


class DistributionIn(StrictModel):
    period_from: date
    period_to: date
    notes: NoteText | None = None


class DistributionReverseIn(StrictModel):
    reason: ReasonText


class DistributionLineOut(BaseModel):
    partner_id: UUID
    partner_name_ar: str
    partner_name_en: str | None
    weight_pct: Decimal
    amount: Money


class DistributionPlanOut(BaseModel):
    """What closing the period will do — the preview shows exactly what is posted."""

    period_from: date
    period_to: date
    profit_policy: Literal["PERIODIC", "PER_CAR"]
    prorata_method: ProrataMethod
    rounding_remainder: RoundingMethod
    loss_handling: Literal["ALLOCATE_TO_PARTNERS", "CARRY_FORWARD"]
    revenue: Money
    expenses: Money
    net_profit: Money
    allocated_in_advance: Money
    carried_in: Money
    distributed: Money
    carried_out: Money
    lines: list[DistributionLineOut]
    summary_ar: str
    summary_en: str


class DistributionOut(DistributionPlanOut):
    id: UUID
    status: Literal["POSTED", "REVERSED"]
    closing_entry_no: int | None
    distribution_entry_no: int | None
    created_at: datetime
    reversal_reason: str | None
    notes: str | None
