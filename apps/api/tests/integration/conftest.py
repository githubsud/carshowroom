"""Integration tests against the local Supabase stack.

Prerequisite: ``supabase start`` and ``supabase db reset`` (seed users and tenants).
Tokens come from real Supabase Auth logins and are verified through the real
JWKS endpoint, exactly as in production.

Set REQUIRE_DB=1 (CI does) to fail instead of skip when the stack is down.
"""

import os
from collections.abc import Iterator
from functools import cache
from pathlib import Path
from typing import Any

import httpx
import psycopg
import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app

_ENV_FILE = Path(__file__).resolve().parents[2] / ".env"

NOUR = "11111111-1111-1111-1111-111111111111"
DOHA = "22222222-2222-2222-2222-222222222222"
PASSWORD = "Demo-Pass-2026"


def _env() -> dict[str, str]:
    values: dict[str, str] = {}
    if _ENV_FILE.exists():
        for line in _ENV_FILE.read_text(encoding="utf-8").splitlines():
            if line and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                values[key.strip()] = value.strip()
    values.update(os.environ)
    return values


ENV = _env()
ADMIN_DB_URL = ENV.get("TEST_ADMIN_DATABASE_URL", "postgresql://postgres:postgres@127.0.0.1:54322/postgres")


def _stack_available() -> bool:
    try:
        with psycopg.connect(ADMIN_DB_URL, connect_timeout=3) as conn:
            row = conn.execute("select count(*) from public.tenants where id = %s", (NOUR,)).fetchone()
            return row == (1,)
    except psycopg.Error:
        return False


@pytest.fixture(scope="session", autouse=True)
def _require_stack() -> None:
    if not _stack_available():
        message = "local Supabase stack with seed data is not available (supabase start && supabase db reset)"
        if ENV.get("REQUIRE_DB") == "1":
            pytest.fail(message)
        pytest.skip(message)


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    for item in items:
        item.add_marker(pytest.mark.db)


@pytest.fixture(scope="session")
def client() -> Iterator[TestClient]:
    settings = Settings(_env_file=_ENV_FILE, environment="testing")  # type: ignore[call-arg]
    with TestClient(create_app(settings)) as test_client:
        yield test_client


@cache
def access_token(email: str) -> str:
    response = httpx.post(
        f"{ENV['SUPABASE_URL']}/auth/v1/token",
        params={"grant_type": "password"},
        headers={"apikey": ENV["SUPABASE_PUBLISHABLE_KEY"]},
        json={"email": email, "password": PASSWORD},
        timeout=10,
    )
    response.raise_for_status()
    token: str = response.json()["access_token"]
    return token


def auth(email: str, tenant_id: str | None = None) -> dict[str, str]:
    headers = {"Authorization": f"Bearer {access_token(email)}"}
    if tenant_id:
        headers["X-Tenant-Id"] = tenant_id
    return headers


@pytest.fixture
def admin_db() -> Iterator[psycopg.Connection[Any]]:
    """Superuser-ish connection for arranging and inspecting state."""
    with psycopg.connect(ADMIN_DB_URL, autocommit=True) as conn:
        yield conn
