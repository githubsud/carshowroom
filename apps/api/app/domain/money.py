"""Money (SPEC §3.3, §11).

* Always ``Decimal``; floats are rejected outright.
* At most 2 decimals and at most 16 integer digits (numeric(18,2)).
  Input with more decimals is rejected, never rounded silently.
* Where the system itself must round (e.g. splitting an amount), it uses
  ROUND_HALF_UP to 2 decimals (DECISIONS A-07): ``quantize``.
* Over JSON, money is a string with exactly 2 decimals: "25000.00".
"""

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Annotated, Literal

from pydantic import AfterValidator, BeforeValidator, PlainSerializer, WithJsonSchema

CENT = Decimal("0.01")
_MAX = Decimal("10") ** 16  # numeric(18,2): 16 integer digits


def parse_money(value: object) -> Decimal:
    """Strict parse: str / int / Decimal with <= 2 decimals; anything else is an error."""
    if isinstance(value, bool | float):
        raise ValueError("money must be a decimal string, not a float")
    if isinstance(value, Decimal):
        amount = value
    elif isinstance(value, int):
        amount = Decimal(value)
    elif isinstance(value, str):
        text = value.strip()
        # Plain decimal notation only: no exponents, no separators.
        if not text or not all(c.isdigit() or c in "-." for c in text):
            raise ValueError("money must be a plain decimal string like 1250.50")
        try:
            amount = Decimal(text)
        except InvalidOperation as exc:
            raise ValueError("money must be a plain decimal string like 1250.50") from exc
    else:
        raise ValueError("money must be a decimal string")

    if not amount.is_finite():
        raise ValueError("money must be finite")
    exponent = amount.as_tuple().exponent
    if isinstance(exponent, int) and exponent < -2 and amount != amount.quantize(CENT):
        raise ValueError("money has more than 2 decimals")
    if abs(amount) >= _MAX:
        raise ValueError("money is too large")
    return amount


def quantize(amount: Decimal) -> Decimal:
    """Round to cents, half up — only where the system computes an amount itself."""
    return amount.quantize(CENT, rounding=ROUND_HALF_UP)


def to_cents_string(amount: Decimal) -> str:
    return f"{amount.quantize(CENT):f}"


def _positive(amount: Decimal) -> Decimal:
    if amount <= 0:
        raise ValueError("money must be greater than zero")
    return amount


_SCHEMA = WithJsonSchema({"type": "string", "pattern": r"^-?\d{1,16}(\.\d{1,2})?$", "examples": ["25000.00"]})

Money = Annotated[Decimal, BeforeValidator(parse_money), PlainSerializer(to_cents_string, return_type=str), _SCHEMA]
PositiveMoney = Annotated[
    Decimal,
    BeforeValidator(parse_money),
    AfterValidator(_positive),
    PlainSerializer(to_cents_string, return_type=str),
    _SCHEMA,
]

_CURRENCY_LABELS: dict[str, dict[str, str]] = {
    "EGP": {"ar": "ج.م", "en": "EGP"},
    "QAR": {"ar": "ر.ق", "en": "QAR"},
    "AED": {"ar": "د.إ", "en": "AED"},
    "SAR": {"ar": "ر.س", "en": "SAR"},
    "SDG": {"ar": "ج.س", "en": "SDG"},
}


def currency_label(currency: str, language: Literal["ar", "en"]) -> str:
    return _CURRENCY_LABELS.get(currency, {}).get(language, currency)


def format_money(amount: Decimal, currency: str, language: Literal["ar", "en"]) -> str:
    """Display text for previews and documents: "25,000.00 ج.م" / "EGP 25,000.00"."""
    text = f"{amount.quantize(CENT):,.2f}"
    label = currency_label(currency, language)
    return f"{text} {label}" if language == "ar" else f"{label} {text}"


def ltr(text: str) -> str:
    """Isolate left-to-right text (dates, codes) inside Arabic sentences, so the
    bidi algorithm does not reorder "2026-10-02" into "02-10-2026"."""
    return f"⁦{text}⁩"
