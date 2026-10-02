"""A test signing key and token minting, standing in for Supabase Auth's JWKS."""

import time
from dataclasses import dataclass
from typing import Any
from uuid import UUID

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa

from app.core.security import TokenVerifier

TEST_KID = "test-key-1"
_PRIVATE_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


@dataclass
class _SigningKey:
    key: Any


class StaticKeySource:
    """Mimics jwt.PyJWKClient for the single test key."""

    def get_signing_key_from_jwt(self, token: str) -> _SigningKey:
        if jwt.get_unverified_header(token).get("kid") != TEST_KID:
            raise jwt.PyJWKClientError("unknown kid")
        return _SigningKey(_PRIVATE_KEY.public_key())


def make_verifier(hs256_secret: str | None = None) -> TokenVerifier:
    return TokenVerifier(audience="authenticated", key_source=StaticKeySource(), hs256_secret=hs256_secret)


def mint_token(
    user_id: UUID | str,
    *,
    email: str | None = None,
    full_name: str | None = None,
    expires_in: int = 3600,
    audience: str = "authenticated",
    role: str = "authenticated",
    kid: str = TEST_KID,
    **extra: Any,
) -> str:
    now = int(time.time())
    claims: dict[str, Any] = {
        "sub": str(user_id),
        "aud": audience,
        "role": role,
        "iat": now,
        "exp": now + expires_in,
        "user_metadata": {"full_name": full_name} if full_name else {},
        **extra,
    }
    if email:
        claims["email"] = email
    return jwt.encode(claims, _PRIVATE_KEY, algorithm="RS256", headers={"kid": kid})
