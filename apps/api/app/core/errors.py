"""Consistent error envelope (SPEC §8, docs/API.md §2).

Every error leaves the API as::

    {"error": {"code": "VEHICLE_ALREADY_SOLD", "message": "...", "details": {}}}

The frontend translates ``code``; ``message`` is English for logs and developers.
Stack traces never reach the client.
"""

import logging
from typing import Any, cast

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.request_context import current_request_id

logger = logging.getLogger(__name__)


class AppError(Exception):
    """A business or access error with a stable, translatable code."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int = 422,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details or {}


# --- Common errors -------------------------------------------------------------


def auth_invalid_token(reason: str = "Invalid or expired token") -> AppError:
    return AppError("AUTH_INVALID_TOKEN", reason, status_code=401)


def tenant_header_missing() -> AppError:
    return AppError("TENANT_HEADER_MISSING", "X-Tenant-Id header is required", status_code=400)


def tenant_access_denied() -> AppError:
    # Same answer whether the tenant exists or not, so ids cannot be probed.
    return AppError("TENANT_ACCESS_DENIED", "No access to this tenant", status_code=403)


def permission_denied(permission: str) -> AppError:
    return AppError(
        "PERMISSION_DENIED",
        f"Missing permission: {permission}",
        status_code=403,
        details={"permission": permission},
    )


def tenant_read_only() -> AppError:
    return AppError("TENANT_READ_ONLY", "The subscription is suspended; the tenant is read-only", status_code=423)


def not_found(entity: str) -> AppError:
    return AppError("NOT_FOUND", f"{entity} not found", status_code=404, details={"entity": entity})


# --- Handlers --------------------------------------------------------------------


def _envelope(code: str, message: str, status_code: int, details: dict[str, Any] | None = None) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"error": {"code": code, "message": message, "details": details or {}}},
    )


async def _app_error_handler(_: Request, exc: Exception) -> JSONResponse:
    exc = cast(AppError, exc)
    return _envelope(exc.code, exc.message, exc.status_code, exc.details)


async def _validation_error_handler(_: Request, exc: Exception) -> JSONResponse:
    exc = cast(RequestValidationError, exc)
    fields: dict[str, list[str]] = {}
    for err in exc.errors():
        # Drop the "body"/"query" prefix: the UI maps errors to form fields.
        location = [str(part) for part in err.get("loc", ())][1:] or ["_"]
        fields.setdefault(".".join(location), []).append(str(err.get("type", "invalid")))
    return _envelope("VALIDATION_ERROR", "Request validation failed", 422, {"fields": fields})


async def _http_error_handler(_: Request, exc: Exception) -> JSONResponse:
    exc = cast(StarletteHTTPException, exc)
    code = {
        404: "NOT_FOUND",
        405: "METHOD_NOT_ALLOWED",
        413: "REQUEST_TOO_LARGE",
        429: "RATE_LIMITED",
    }.get(exc.status_code, "HTTP_ERROR")
    return _envelope(code, str(exc.detail), exc.status_code)


async def _unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    # The database refuses writes to a suspended showroom on its own (SR040, D-113).
    if getattr(getattr(exc, "orig", None), "sqlstate", None) == "SR040":
        error = tenant_read_only()
        return _envelope(error.code, error.message, error.status_code)
    request_id = getattr(request.state, "request_id", None) or current_request_id()
    logger.exception("unhandled error", exc_info=exc, extra={"event": "unhandled_error"})
    response = _envelope("INTERNAL_ERROR", "An unexpected error occurred", 500, {"request_id": request_id})
    if request_id:
        response.headers["X-Request-Id"] = request_id
    return response


# Public name for the request middleware, which renders unhandled errors inside CORS.
unhandled_error_response = _unhandled_error_handler


def register_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AppError, _app_error_handler)
    app.add_exception_handler(RequestValidationError, _validation_error_handler)
    app.add_exception_handler(StarletteHTTPException, _http_error_handler)
    app.add_exception_handler(Exception, _unhandled_error_handler)
