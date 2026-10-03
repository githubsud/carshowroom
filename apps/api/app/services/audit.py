"""Business events for the audit log (row changes are captured by DB triggers)."""

import json
from typing import Any
from uuid import UUID

from sqlalchemy import Connection, text

from app.core.request_context import current_client

_INSERT_EVENT = text(
    """
    insert into public.audit_log
      (tenant_id, actor_user_id, actor_kind, action, entity_type, entity_id,
       details, ip, user_agent, request_id)
    values
      (:tenant_id, :actor, :actor_kind, :action, :entity_type, :entity_id, cast(:details as jsonb),
       cast(:ip as inet), :user_agent, :request_id)
    """
)


def record_event(
    conn: Connection,
    *,
    tenant_id: UUID | None,
    actor: UUID | None,
    action: str,
    entity_type: str | None = None,
    entity_id: str | None = None,
    details: dict[str, Any] | None = None,
    actor_kind: str = "USER",
) -> None:
    client = current_client()
    conn.execute(
        _INSERT_EVENT,
        {
            "tenant_id": tenant_id,
            "actor": actor,
            "actor_kind": actor_kind,
            "action": action,
            "entity_type": entity_type,
            "entity_id": entity_id,
            "details": json.dumps(details or {}, ensure_ascii=False),
            "ip": client.ip if client else None,
            "user_agent": client.user_agent if client else None,
            "request_id": client.request_id if client else None,
        },
    )
