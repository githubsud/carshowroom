"""Plan limits and feature flags (SPEC §4.16, BACKLOG 9.1).

Limits come from the tenant's plan (`plans.limits`): users, branches and
vehicles in stock. Reaching one refuses the action with PLAN_LIMIT_REACHED;
nothing that already exists is touched.
"""

from typing import Literal

from sqlalchemy import Connection, text

from app.core.errors import AppError

LimitKey = Literal["users", "branches", "vehicles_in_stock"]

_USAGE: dict[LimitKey, str] = {
    "users": (
        "select count(*) from public.memberships where tenant_id = private.current_tenant_id() and status = 'ACTIVE'"
    ),
    "branches": (
        "select count(*) from public.branches where tenant_id = private.current_tenant_id() and archived_at is null"
    ),
    "vehicles_in_stock": (
        "select count(*) from public.vehicles where tenant_id = private.current_tenant_id() "
        "and status in ('DRAFT', 'IN_PREPARATION', 'AVAILABLE', 'RESERVED', 'AT_OTHER_SHOWROOM')"
    ),
}


def limit(conn: Connection, key: LimitKey) -> int | None:
    value = conn.execute(
        text(
            "select (p.limits ->> :key)::int from public.subscriptions s join public.plans p on p.id = s.plan_id "
            "where s.tenant_id = private.current_tenant_id()"
        ),
        {"key": key},
    ).scalar_one_or_none()
    return int(value) if value is not None else None


def usage(conn: Connection, key: LimitKey) -> int:
    return int(conn.execute(text(_USAGE[key])).scalar_one())


def ensure_room(conn: Connection, key: LimitKey, adding: int = 1) -> None:
    """Refuse when `adding` more would pass the plan's limit."""
    maximum = limit(conn, key)
    if maximum is None:
        return
    used = usage(conn, key)
    if used + adding > maximum:
        raise AppError(
            "PLAN_LIMIT_REACHED",
            "Your plan's limit is reached; upgrade the plan to add more",
            status_code=403,
            details={"limit": key, "max": maximum, "used": used},
        )


def ensure_feature(conn: Connection, flag: str) -> None:
    enabled = conn.execute(
        text("select private.feature_enabled(private.current_tenant_id(), :flag)"), {"flag": flag}
    ).scalar_one()
    if not enabled:
        raise AppError(
            "FEATURE_DISABLED", "This module is not enabled for this showroom", status_code=403, details={"flag": flag}
        )
