import time
import uuid

import jwt
import pytest

from app.core.errors import AppError
from tests.keys import make_verifier, mint_token

USER_ID = uuid.uuid4()


def test_valid_asymmetric_token_is_accepted() -> None:
    user = make_verifier().verify(mint_token(USER_ID, email="owner@example.com"))
    assert user.id == USER_ID
    assert user.email == "owner@example.com"


@pytest.mark.parametrize(
    ("token_kwargs", "reason"),
    [
        ({"expires_in": -10}, "expired"),
        ({"audience": "other"}, "wrong audience"),
        ({"role": "anon"}, "anon key token"),
        ({"role": "service_role"}, "service role token"),
        ({"kid": "unknown"}, "unknown signing key"),
    ],
)
def test_invalid_tokens_are_rejected(token_kwargs: dict[str, object], reason: str) -> None:
    with pytest.raises(AppError) as err:
        make_verifier().verify(mint_token(USER_ID, **token_kwargs))  # type: ignore[arg-type]
    assert err.value.code == "AUTH_INVALID_TOKEN", reason
    assert err.value.status_code == 401


def test_garbage_token_is_rejected() -> None:
    with pytest.raises(AppError) as err:
        make_verifier().verify("not-a-jwt")
    assert err.value.code == "AUTH_INVALID_TOKEN"


def _hs256_token(secret: str) -> str:
    now = int(time.time())
    return jwt.encode(
        {"sub": str(USER_ID), "aud": "authenticated", "role": "authenticated", "iat": now, "exp": now + 60},
        secret,
        algorithm="HS256",
    )


def test_hs256_requires_a_configured_secret() -> None:
    token = _hs256_token("x" * 40)
    with pytest.raises(AppError):
        make_verifier().verify(token)
    assert make_verifier(hs256_secret="x" * 40).verify(token).id == USER_ID


def test_hs256_with_wrong_secret_is_rejected() -> None:
    with pytest.raises(AppError):
        make_verifier(hs256_secret="y" * 40).verify(_hs256_token("x" * 40))


def test_unsigned_token_is_rejected() -> None:
    token = jwt.encode(
        {"sub": str(USER_ID), "aud": "authenticated", "role": "authenticated", "exp": int(time.time()) + 60},
        key=None,
        algorithm="none",
    )
    with pytest.raises(AppError):
        make_verifier(hs256_secret="x" * 40).verify(token)


def test_subject_must_be_a_uuid() -> None:
    with pytest.raises(AppError):
        make_verifier().verify(mint_token("not-a-uuid"))
