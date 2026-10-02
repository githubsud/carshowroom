"""HTTP-level behaviour that needs no database: auth, headers, error envelope."""

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi import APIRouter
from fastapi.testclient import TestClient
from pydantic import BaseModel, ConfigDict

from app.core.config import Settings
from app.core.errors import AppError
from app.main import create_app
from tests.keys import make_verifier, mint_token


class _EchoIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    amount: int


class _NoDatabase:
    """Fails loudly if a test path reaches the database."""

    def transaction(self, **_: Any) -> Any:
        raise AssertionError("database must not be reached")

    def ping(self) -> bool:
        raise ConnectionError("no database")


@pytest.fixture
def client() -> Iterator[TestClient]:
    settings = Settings(
        environment="testing",
        database_url="postgresql://unused@localhost/unused",
        supabase_url="http://localhost:54321",
    )
    app = create_app(settings, database=_NoDatabase(), token_verifier=make_verifier())  # type: ignore[arg-type]

    boom = APIRouter()

    @boom.get("/boom")
    def _boom() -> None:
        raise RuntimeError("secret internal detail")

    @boom.get("/business-error")
    def _business_error() -> None:
        raise AppError("VEHICLE_ALREADY_SOLD", "Vehicle already sold", status_code=409, details={"id": "v1"})

    @boom.post("/echo")
    def _echo(body: _EchoIn) -> _EchoIn:
        return body

    app.include_router(boom)
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client


def test_healthz(client: TestClient) -> None:
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert response.headers["X-Request-Id"]


def test_readyz_reports_unavailable_database(client: TestClient) -> None:
    assert client.get("/readyz").status_code == 503


def test_missing_token_returns_401_envelope(client: TestClient) -> None:
    response = client.get("/api/v1/me")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTH_INVALID_TOKEN"


def test_tenant_endpoint_requires_tenant_header(client: TestClient) -> None:
    token = mint_token("00000000-0000-0000-0000-000000000001")
    response = client.get("/api/v1/tenant", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "TENANT_HEADER_MISSING"


def test_malformed_tenant_header_is_access_denied(client: TestClient) -> None:
    token = mint_token("00000000-0000-0000-0000-000000000001")
    response = client.get(
        "/api/v1/tenant", headers={"Authorization": f"Bearer {token}", "X-Tenant-Id": "not-a-uuid"}
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "TENANT_ACCESS_DENIED"


def test_business_error_envelope(client: TestClient) -> None:
    response = client.get("/business-error")
    assert response.status_code == 409
    assert response.json() == {
        "error": {"code": "VEHICLE_ALREADY_SOLD", "message": "Vehicle already sold", "details": {"id": "v1"}}
    }


def test_unhandled_error_hides_internals(client: TestClient) -> None:
    response = client.get("/boom", headers={"X-Request-Id": "req-123"})
    assert response.status_code == 500
    body = response.json()
    assert body["error"]["code"] == "INTERNAL_ERROR"
    assert body["error"]["details"] == {"request_id": "req-123"}
    assert "secret internal detail" not in response.text


def test_unknown_route_uses_envelope(client: TestClient) -> None:
    response = client.get("/api/v1/does-not-exist")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


def test_validation_error_envelope(client: TestClient) -> None:
    response = client.post("/echo", json={"amount": "not-a-number", "extra": 1})
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "VALIDATION_ERROR"
    assert set(error["details"]["fields"]) == {"amount", "extra"}


def test_openapi_is_disabled_in_production() -> None:
    settings = Settings(
        environment="production",
        database_url="postgresql://unused@localhost/unused",
        supabase_url="http://localhost:54321",
    )
    app = create_app(settings, database=_NoDatabase(), token_verifier=make_verifier())  # type: ignore[arg-type]
    with TestClient(app) as test_client:
        assert test_client.get("/api/v1/openapi.json").status_code == 404
