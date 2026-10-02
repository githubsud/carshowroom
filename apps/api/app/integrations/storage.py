"""Supabase Storage through short-lived signed URLs (ARCHITECTURE §8, D-15, D-74).

Buckets are private and have no browser policies: the API (service-role key,
server-side only) issues a 15-minute upload URL or 5-minute view URLs after
checking the user's permissions. The browser never lists or reads a bucket.
"""

from typing import Protocol

import httpx

from app.core.errors import AppError

UPLOAD_TTL_SECONDS = 15 * 60
VIEW_TTL_SECONDS = 5 * 60


class Storage(Protocol):
    def upload_url(self, bucket: str, path: str) -> str: ...

    def view_urls(self, bucket: str, paths: list[str]) -> dict[str, str]: ...

    def exists(self, bucket: str, path: str) -> bool: ...


class SupabaseStorage:
    def __init__(self, *, supabase_url: str, public_url: str, service_role_key: str, timeout: float = 10.0) -> None:
        self._base = supabase_url.rstrip("/") + "/storage/v1"
        self._public = public_url.rstrip("/") + "/storage/v1"
        self._headers = {"apikey": service_role_key}
        if not service_role_key.startswith("sb_"):
            self._headers["Authorization"] = f"Bearer {service_role_key}"
        self._timeout = timeout

    def _post(self, url: str, json: dict[str, object]) -> httpx.Response:
        try:
            response = httpx.post(url, headers=self._headers, json=json, timeout=self._timeout)
        except httpx.HTTPError as exc:
            raise storage_unavailable() from exc
        if response.status_code >= 500:
            raise storage_unavailable()
        return response

    def upload_url(self, bucket: str, path: str) -> str:
        response = self._post(f"{self._base}/object/upload/sign/{bucket}/{path}", {})
        if response.status_code >= 400:
            raise storage_unavailable()
        signed: str = response.json()["url"]
        return self._public + signed

    def view_urls(self, bucket: str, paths: list[str]) -> dict[str, str]:
        if not paths:
            return {}
        response = self._post(f"{self._base}/object/sign/{bucket}", {"expiresIn": VIEW_TTL_SECONDS, "paths": paths})
        if response.status_code >= 400:
            raise storage_unavailable()
        return {
            item["path"]: self._public + item["signedURL"]
            for item in response.json()
            if item.get("signedURL") and not item.get("error")
        }

    def exists(self, bucket: str, path: str) -> bool:
        return path in self.view_urls(bucket, [path])


class DisabledStorage:
    """Used when no service-role key is configured: uploads fail, nothing is shown."""

    def upload_url(self, bucket: str, path: str) -> str:
        raise storage_unavailable()

    def view_urls(self, bucket: str, paths: list[str]) -> dict[str, str]:
        return {}

    def exists(self, bucket: str, path: str) -> bool:
        return False


def storage_unavailable() -> AppError:
    return AppError("STORAGE_UNAVAILABLE", "File storage is not available", status_code=503)
