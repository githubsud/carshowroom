"""Supabase JWT verification (ARCHITECTURE §4.4).

Asymmetric tokens (RS256/ES256) are verified against the project's JWKS.
HS256 is accepted only when a legacy JWT secret is configured explicitly.
"""

from dataclasses import dataclass, field
from typing import Any, Protocol
from uuid import UUID

import jwt

from app.core.errors import auth_invalid_token

ASYMMETRIC_ALGORITHMS = frozenset({"RS256", "ES256"})


class SigningKeySource(Protocol):
    """What we need from jwt.PyJWKClient; tests substitute a static key."""

    def get_signing_key_from_jwt(self, token: str) -> Any: ...


@dataclass(frozen=True)
class AuthenticatedUser:
    id: UUID
    email: str | None
    claims: dict[str, Any] = field(repr=False)


class TokenVerifier:
    def __init__(
        self,
        *,
        audience: str,
        key_source: SigningKeySource | None = None,
        hs256_secret: str | None = None,
    ) -> None:
        self._audience = audience
        self._key_source = key_source
        self._hs256_secret = hs256_secret

    def verify(self, token: str) -> AuthenticatedUser:
        try:
            header = jwt.get_unverified_header(token)
        except jwt.PyJWTError as exc:
            raise auth_invalid_token("Malformed token") from exc

        algorithm = header.get("alg")
        key: Any
        if algorithm in ASYMMETRIC_ALGORITHMS and self._key_source is not None:
            try:
                key = self._key_source.get_signing_key_from_jwt(token).key
            except jwt.PyJWTError as exc:
                raise auth_invalid_token("Unknown signing key") from exc
        elif algorithm == "HS256" and self._hs256_secret:
            key = self._hs256_secret
        else:
            raise auth_invalid_token("Unsupported token algorithm")

        try:
            claims: dict[str, Any] = jwt.decode(
                token,
                key,
                algorithms=[algorithm],
                audience=self._audience,
                options={"require": ["exp", "sub", "aud"]},
            )
        except jwt.ExpiredSignatureError as exc:
            raise auth_invalid_token("Token expired") from exc
        except jwt.PyJWTError as exc:
            raise auth_invalid_token() from exc

        if claims.get("role") != "authenticated":
            raise auth_invalid_token("Not an authenticated user token")
        try:
            user_id = UUID(str(claims["sub"]))
        except ValueError as exc:
            raise auth_invalid_token("Invalid subject") from exc

        email = claims.get("email")
        return AuthenticatedUser(id=user_id, email=email if isinstance(email, str) else None, claims=claims)


def build_token_verifier(*, jwks_url: str, audience: str, hs256_secret: str | None) -> TokenVerifier:
    # PyJWKClient caches keys and refetches on an unknown kid (key rotation).
    return TokenVerifier(
        audience=audience,
        key_source=jwt.PyJWKClient(jwks_url, cache_keys=True, lifespan=600),
        hs256_secret=hs256_secret,
    )


__all__ = ["AuthenticatedUser", "TokenVerifier", "build_token_verifier"]
