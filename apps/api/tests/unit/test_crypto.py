import pytest

from app.core.crypto import FieldCipher, mask, new_key
from app.core.errors import AppError


def test_round_trip_and_context_binding() -> None:
    cipher = FieldCipher(new_key())
    token = cipher.encrypt("29001011234567", context="partner:a")
    assert token.startswith("v1:")
    assert "29001011234567" not in token
    assert cipher.decrypt(token, context="partner:a") == "29001011234567"
    with pytest.raises(AppError) as err:
        cipher.decrypt(token, context="partner:b")  # copied onto another record
    assert err.value.code == "DECRYPTION_FAILED"


def test_same_value_encrypts_differently_each_time() -> None:
    cipher = FieldCipher(new_key())
    assert cipher.encrypt("123", context="x") != cipher.encrypt("123", context="x")


def test_without_a_key_storage_is_refused() -> None:
    with pytest.raises(AppError) as err:
        FieldCipher(None).encrypt("123", context="x")
    assert err.value.code == "ENCRYPTION_UNAVAILABLE"


def test_bad_key_length_is_rejected_at_startup() -> None:
    with pytest.raises(ValueError, match="32 bytes"):
        FieldCipher("c2hvcnQ=")


def test_mask() -> None:
    assert mask("4567") == "••••4567"
    assert mask(None) is None
