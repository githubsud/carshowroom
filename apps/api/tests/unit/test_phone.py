import pytest

from app.core.errors import AppError
from app.core.phone import normalize_phone, phone_digits


@pytest.mark.parametrize(
    ("raw", "country", "expected"),
    [
        ("0100 123 4567", "EG", "+201001234567"),
        ("01001234567", "EG", "+201001234567"),
        ("٠١٠٠١٢٣٤٥٦٧", "EG", "+201001234567"),
        ("+20 100 123 4567", "EG", "+201001234567"),
        ("00201001234567", "EG", "+201001234567"),
        ("02 2345 6789", "EG", "+20223456789"),
        ("5512 3456", "QA", "+97455123456"),
        ("+974 5512 3456", "QA", "+97455123456"),
        # A Qatari number saved by an Egyptian showroom keeps its own prefix.
        ("+974 5512 3456", "EG", "+97455123456"),
    ],
)
def test_normalizes_to_e164(raw: str, country: str, expected: str) -> None:
    assert normalize_phone(raw, country) == expected


@pytest.mark.parametrize(("raw", "country"), [("123", "EG"), ("0100 12", "EG"), ("5512 34", "QA"), ("+20 999", "QA")])
def test_rejects_invalid_numbers(raw: str, country: str) -> None:
    with pytest.raises(AppError) as error:
        normalize_phone(raw, country)
    assert error.value.code == "PHONE_INVALID"


def test_search_digits_drop_the_local_zero() -> None:
    assert phone_digits("0100 123") == "100123"
    assert phone_digits("+20100") == "20100"
