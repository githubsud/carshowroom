"""Field encryption for sensitive personal data (SPEC §10, DECISIONS D-05).

National IDs are encrypted with AES-256-GCM before they reach the database;
only the API holds the key. Stored format: "v1:<base64(nonce || ciphertext)>".
"""

import base64
import secrets

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.core.errors import AppError

_PREFIX = "v1:"


def _unavailable() -> AppError:
    return AppError("ENCRYPTION_UNAVAILABLE", "National IDs cannot be stored on this server", status_code=503)


class FieldCipher:
    def __init__(self, key_b64: str | None) -> None:
        self._aead: AESGCM | None = None
        if key_b64:
            key = base64.b64decode(key_b64)
            if len(key) != 32:
                raise ValueError("NATIONAL_ID_KEY must be 32 bytes, base64-encoded")
            self._aead = AESGCM(key)

    def encrypt(self, plaintext: str, *, context: str) -> str:
        """`context` (e.g. "partner:<id>") is bound as associated data, so a
        ciphertext copied to another record does not decrypt."""
        if self._aead is None:
            raise _unavailable()
        nonce = secrets.token_bytes(12)
        sealed = self._aead.encrypt(nonce, plaintext.encode(), context.encode())
        return _PREFIX + base64.b64encode(nonce + sealed).decode()

    def decrypt(self, token: str, *, context: str) -> str:
        if self._aead is None:
            raise _unavailable()
        if not token.startswith(_PREFIX):
            raise ValueError("unknown ciphertext format")
        raw = base64.b64decode(token[len(_PREFIX) :])
        try:
            return self._aead.decrypt(raw[:12], raw[12:], context.encode()).decode()
        except InvalidTag as exc:
            raise AppError("DECRYPTION_FAILED", "The stored value cannot be decrypted", status_code=500) from exc


def new_key() -> str:
    return base64.b64encode(secrets.token_bytes(32)).decode()


def mask(last4: str | None) -> str | None:
    return f"••••{last4}" if last4 else None
