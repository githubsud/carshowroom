"""Money handling (SPEC §3.3, §11): Decimal only, 2 decimals, never rounded silently."""

from decimal import Decimal

import pytest
from pydantic import BaseModel, ValidationError

from app.domain.money import Money, PositiveMoney, format_money, parse_money, quantize


class _Body(BaseModel):
    amount: PositiveMoney
    balance: Money


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("25000", Decimal("25000.00")),
        ("25000.5", Decimal("25000.50")),
        ("0.01", Decimal("0.01")),
        (7, Decimal("7")),
    ],
)
def test_parse_accepts_strings_and_ints(raw: object, expected: Decimal) -> None:
    assert parse_money(raw) == expected


@pytest.mark.parametrize("raw", ["10.005", "1e3", "abc", "NaN", "Infinity", "", 10.5, True, "10,000.00"])
def test_parse_rejects_floats_extra_decimals_and_garbage(raw: object) -> None:
    with pytest.raises(ValueError, match="money"):
        parse_money(raw)


def test_parse_rejects_values_beyond_numeric_18_2() -> None:
    with pytest.raises(ValueError, match="money"):
        parse_money("10000000000000000.00")  # 17 integer digits
    assert parse_money("9999999999999999.99") == Decimal("9999999999999999.99")


def test_quantize_is_half_up() -> None:
    assert quantize(Decimal("2.345")) == Decimal("2.35")
    assert quantize(Decimal("2.335")) == Decimal("2.34")  # banker's rounding would give 2.34 too
    assert quantize(Decimal("2.325")) == Decimal("2.33")  # banker's would give 2.32
    assert quantize(Decimal("-2.325")) == Decimal("-2.33")


def test_pydantic_money_serialises_as_two_decimal_string() -> None:
    body = _Body(amount="25000", balance="-10.5")  # type: ignore[arg-type]
    assert body.model_dump(mode="json") == {"amount": "25000.00", "balance": "-10.50"}


def test_positive_money_rejects_zero_and_negative() -> None:
    for value in ("0", "0.00", "-1.00"):
        with pytest.raises(ValidationError):
            _Body(amount=value, balance="0")  # type: ignore[arg-type]


def test_format_money_for_previews() -> None:
    assert format_money(Decimal("25000"), "EGP", "ar") == "25,000.00 ج.م"
    assert format_money(Decimal("1250.5"), "QAR", "en") == "QAR 1,250.50"
    assert format_money(Decimal("-10"), "XYZ", "en") == "XYZ -10.00"
