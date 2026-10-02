"""Phone normalisation to E.164 (SPEC §4.6: phone-first customer search).

Only the formats used in the launch countries are recognised (country pack):
Egypt (+20, mobile 01x xxxx xxxx) and Qatar (+974, 8 digits). Anything else
must already carry an international prefix. Arabic-Indic digits are accepted.
"""

import re

from app.core.errors import AppError

_ARABIC_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")
_COUNTRY_CODES = {"EG": "20", "QA": "974"}


def normalize_phone(raw: str, country_code: str) -> str:
    """'0100 123 4567' (EG) -> '+201001234567'; '5512 3456' (QA) -> '+97455123456'."""
    text = raw.translate(_ARABIC_DIGITS).strip()
    international = text.startswith(("+", "00"))
    digits = re.sub(r"\D", "", text)
    if text.startswith("00"):
        digits = digits[2:]
    if not international:
        local = _COUNTRY_CODES.get(country_code)
        if local == "20" and digits.startswith("0"):
            digits = local + digits[1:]
        elif local == "974" and len(digits) == 8:
            digits = local + digits
        elif local and not digits.startswith(local):
            raise invalid_phone(raw)
    if not 8 <= len(digits) <= 15:
        raise invalid_phone(raw)
    if digits.startswith("20") and not re.fullmatch(r"20(1[0125]\d{8}|[2-9]\d{7,9})", digits):
        raise invalid_phone(raw)
    if digits.startswith("974") and len(digits) != 11:
        raise invalid_phone(raw)
    return "+" + digits


def phone_digits(query: str) -> str:
    """Digits of a search query, so '0100 123' finds '+20100123...'."""
    digits = re.sub(r"\D", "", query.translate(_ARABIC_DIGITS))
    return digits[1:] if digits.startswith("0") and not digits.startswith("00") else digits


def invalid_phone(raw: str) -> AppError:
    return AppError("PHONE_INVALID", "The phone number is not valid", status_code=422, details={"phone": raw})
