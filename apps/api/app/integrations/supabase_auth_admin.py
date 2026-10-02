"""Supabase Auth admin calls (service-role key, server-side only; SPEC §10)."""

from typing import Protocol
from uuid import UUID

import httpx

from app.core.errors import AppError


class AuthAdmin(Protocol):
    def invite_user(self, *, email: str, full_name: str | None, redirect_to: str) -> UUID: ...


class SupabaseAuthAdmin:
    def __init__(self, *, supabase_url: str, service_role_key: str, timeout: float = 10.0) -> None:
        self._base = supabase_url.rstrip("/") + "/auth/v1"
        self._headers = {"apikey": service_role_key}
        # New-style secret keys (sb_secret_...) go in the apikey header only; the
        # gateway exchanges them. Legacy service-role JWTs are also sent as Bearer.
        if not service_role_key.startswith("sb_"):
            self._headers["Authorization"] = f"Bearer {service_role_key}"
        self._timeout = timeout

    def invite_user(self, *, email: str, full_name: str | None, redirect_to: str) -> UUID:
        """Create the account and send the invitation email; returns the new user id."""
        response = httpx.post(
            f"{self._base}/invite",
            params={"redirect_to": redirect_to},
            headers=self._headers,
            json={"email": email, "data": {"full_name": full_name} if full_name else {}},
            timeout=self._timeout,
        )
        if response.status_code >= 400:
            raise AppError(
                "INVITE_FAILED",
                "The invitation could not be sent",
                status_code=502,
                details={"auth_status": response.status_code},
            )
        return UUID(response.json()["id"])


class DisabledAuthAdmin:
    """Used when no service-role key is configured."""

    def invite_user(self, *, email: str, full_name: str | None, redirect_to: str) -> UUID:
        raise AppError("INVITES_DISABLED", "User invitations are not configured", status_code=503)
