"""HTTP hardening (BACKLOG 9.8): request size limit, rate limits and security
headers. In-memory limits are per API instance; behind several instances the
proxy's limits (or a shared store) take over (SECURITY.md)."""

import time
from collections import defaultdict, deque
from collections.abc import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp

MAX_BODY_BYTES = 10 * 1024 * 1024  # an import file (≤ ~7 MB as base64) is the largest body

# (requests, seconds) per client IP; the tightest matching rule wins.
_LIMITS: list[tuple[str, str, int, int]] = [
    ("POST", "/api/v1/signup", 5, 3600),
    ("POST", "/api/v1/users/invite", 30, 3600),
    ("POST", "/api/v1/imports", 30, 3600),
    ("*", "/api/v1/", 600, 60),
]


def _error(status: int, code: str, message: str, headers: dict[str, str] | None = None) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"error": {"code": code, "message": message, "details": {}}},
        headers=headers,
    )


class HttpGuardMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp, *, production: bool, rate_limits: bool = True) -> None:
        super().__init__(app)
        self.production = production
        self.rate_limits = rate_limits
        self._hits: dict[tuple[str, str], deque[float]] = defaultdict(deque)

    def _limited(self, request: Request) -> int | None:
        """Seconds to wait when the client is over a limit, else None."""
        client = request.client.host if request.client else "unknown"
        path, method = request.url.path, request.method
        now = time.monotonic()
        for rule_method, prefix, count, seconds in _LIMITS:
            if (rule_method in ("*", method)) and path.startswith(prefix):
                hits = self._hits[(client, prefix + rule_method)]
                while hits and hits[0] <= now - seconds:
                    hits.popleft()
                if len(hits) >= count:
                    return int(seconds - (now - hits[0])) + 1
                hits.append(now)
                return None
        return None

    async def dispatch(self, request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        length = request.headers.get("content-length")
        if length and length.isdigit() and int(length) > MAX_BODY_BYTES:
            return _error(413, "REQUEST_TOO_LARGE", "The request is too large")
        if self.rate_limits and request.method != "OPTIONS":
            wait = self._limited(request)
            if wait is not None:
                return _error(429, "RATE_LIMITED", "Too many requests; try again shortly", {"Retry-After": str(wait)})
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        if not request.url.path.startswith("/api/v1/docs") and not request.url.path.endswith("openapi.json"):
            response.headers.setdefault("Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'")
        if self.production:
            response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        return response
