"""Idempotency for money-moving POSTs (SPEC §3.3, DECISIONS D-17).

The client sends ``Idempotency-Key`` (one UUID per form submission, reused on
retries). The stored response is written in the same transaction as the
operation, so:

* a retry after success replays the original response (same status and body);
* a retry after failure runs again (the key rolled back with the operation);
* a concurrent duplicate waits on the key, then gets IDEMPOTENCY_IN_PROGRESS
  and replays on its next retry;
* reusing a key for a different request is refused.
"""

import hashlib
import json
from collections.abc import Callable
from typing import Any
from uuid import UUID

from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import Connection, text
from sqlalchemy.exc import IntegrityError

from app.core.errors import AppError
from app.db.session import Database

REPLAY_HEADER = "Idempotent-Replay"


def request_hash(endpoint: str, payload: BaseModel | dict[str, Any] | None) -> str:
    body = payload.model_dump(mode="json") if isinstance(payload, BaseModel) else (payload or {})
    canonical = json.dumps({"endpoint": endpoint, "body": body}, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def _validate_key(key: str | None) -> str:
    if not key:
        raise AppError("IDEMPOTENCY_KEY_REQUIRED", "Idempotency-Key header is required", status_code=400)
    if not 8 <= len(key) <= 128 or not key.isprintable():
        raise AppError("IDEMPOTENCY_KEY_INVALID", "Idempotency-Key must be 8-128 printable characters", status_code=400)
    return key


def run(
    db: Database,
    *,
    user_id: UUID,
    tenant_id: UUID,
    key: str | None,
    endpoint: str,
    payload: BaseModel | dict[str, Any] | None,
    operation: Callable[[Connection], BaseModel],
    status_code: int = 201,
) -> JSONResponse:
    key = _validate_key(key)
    digest = request_hash(endpoint, payload)
    with db.transaction(user_id=user_id, tenant_id=tenant_id) as conn:
        stored = conn.execute(
            text(
                "select user_id, request_hash, response_code, response_body from public.idempotency_keys "
                "where key = :key"
            ),
            {"key": key},
        ).first()
        if stored is not None:
            if stored.request_hash != digest or stored.user_id != user_id:
                raise AppError(
                    "IDEMPOTENCY_KEY_REUSED",
                    "This Idempotency-Key was used for a different request",
                    status_code=409,
                )
            return JSONResponse(stored.response_body, status_code=stored.response_code, headers={REPLAY_HEADER: "true"})

        result = operation(conn)
        body = result.model_dump(mode="json")
        try:
            with conn.begin_nested():
                conn.execute(
                    text(
                        """
                        insert into public.idempotency_keys
                          (tenant_id, key, user_id, endpoint, request_hash, response_code, response_body)
                        values (private.current_tenant_id(), :key, :user_id, :endpoint, :hash, :code,
                                cast(:body as jsonb))
                        """
                    ),
                    {
                        "key": key,
                        "user_id": user_id,
                        "endpoint": endpoint,
                        "hash": digest,
                        "code": status_code,
                        "body": json.dumps(body),
                    },
                )
        except IntegrityError as exc:
            # Another request with this key committed meanwhile; ours must not count twice.
            raise AppError(
                "IDEMPOTENCY_IN_PROGRESS",
                "A request with this Idempotency-Key is already being processed",
                status_code=409,
            ) from exc
    return JSONResponse(body, status_code=status_code)
