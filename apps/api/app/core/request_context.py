"""Per-request metadata (request id, client) used by logging and the audit trail."""

import ipaddress
import uuid
from collections.abc import Awaitable, Callable
from contextvars import ContextVar
from dataclasses import dataclass

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

REQUEST_ID_HEADER = "X-Request-Id"


@dataclass(frozen=True)
class ClientInfo:
    request_id: str
    ip: str | None
    user_agent: str | None


_client: ContextVar[ClientInfo | None] = ContextVar("client_info", default=None)


def current_client() -> ClientInfo | None:
    return _client.get()


def current_request_id() -> str | None:
    client = _client.get()
    return client.request_id if client else None


def _safe_request_id(value: str | None) -> str:
    # Accept a caller-supplied id only if it is short and printable.
    if value and len(value) <= 64 and value.isprintable():
        return value
    return uuid.uuid4().hex


def _valid_ip(host: str | None) -> str | None:
    # Stored as inet in the audit log; an unparsable value must never block a write.
    if not host:
        return None
    try:
        return str(ipaddress.ip_address(host))
    except ValueError:
        return None


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        info = ClientInfo(
            request_id=_safe_request_id(request.headers.get(REQUEST_ID_HEADER)),
            ip=_valid_ip(request.client.host if request.client else None),
            user_agent=(request.headers.get("user-agent") or "")[:512] or None,
        )
        # Also on request.state: unhandled errors are rendered by Starlette's
        # outermost middleware, after this context variable has been reset.
        request.state.request_id = info.request_id
        token = _client.set(info)
        try:
            response = await call_next(request)
        except Exception as exc:
            # Render the 500 here, inside CORS, so the browser sees the real error
            # instead of a blocked cross-origin reply ("cannot reach the server").
            from app.core.errors import unhandled_error_response

            response = await unhandled_error_response(request, exc)
        finally:
            _client.reset(token)
        response.headers[REQUEST_ID_HEADER] = info.request_id
        return response
