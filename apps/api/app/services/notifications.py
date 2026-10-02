"""In-app notifications (SPEC §4.17) and the daily installment reminders
(SPEC §4.8, BACKLOG 5.7).

Notifications go to every active member who holds the relevant permission.
Each has a dedupe key, so the same reminder is never created twice for a user.
"""

import json
from datetime import date, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import Connection, text

from app.domain.installments import NotificationOut, NotificationPage
from app.integrations.messaging import MessageProvider


def notify_permission(
    conn: Connection,
    *,
    permission: str,
    kind: str,
    params: dict[str, Any],
    entity_type: str | None,
    entity_id: UUID | None,
    dedupe_key: str,
) -> int:
    """One notification per member holding `permission`; returns how many were new."""
    result = conn.execute(
        text(
            """
            insert into public.notifications (tenant_id, user_id, kind, params, entity_type, entity_id, dedupe_key)
            select m.tenant_id, m.user_id, :kind, cast(:params as jsonb), :entity_type, :entity_id, :dedupe
              from public.memberships m
             where m.tenant_id = private.current_tenant_id() and m.status = 'ACTIVE'
               and :permission = any (private.effective_permissions(m.tenant_id, m.user_id))
            on conflict (tenant_id, user_id, dedupe_key) do nothing
            """
        ),
        {
            "kind": kind,
            "params": _json(params),
            "entity_type": entity_type,
            "entity_id": entity_id,
            "dedupe": dedupe_key,
            "permission": permission,
        },
    )
    return result.rowcount or 0


def _json(params: dict[str, Any]) -> str:
    return json.dumps(params, ensure_ascii=False, default=str)


def list_for_user(conn: Connection, user_id: UUID, *, unread_only: bool, limit: int) -> NotificationPage:
    rows = conn.execute(
        text(
            """
            select id, kind, params, entity_type, entity_id, read_at is not null as read, created_at
              from public.notifications
             where user_id = :user and (not :unread or read_at is null)
             order by created_at desc
             limit :limit
            """
        ),
        {"user": user_id, "unread": unread_only, "limit": limit},
    ).mappings()
    unread = conn.execute(
        text("select count(*) from public.notifications where user_id = :user and read_at is null"), {"user": user_id}
    ).scalar_one()
    return NotificationPage(items=[NotificationOut.model_validate(dict(r)) for r in rows], unread=unread)


def mark_read(conn: Connection, user_id: UUID, notification_id: UUID | None) -> None:
    conn.execute(
        text(
            "update public.notifications set read_at = now() where user_id = :user and read_at is null "
            "and (cast(:id as uuid) is null or id = :id)"
        ),
        {"user": user_id, "id": notification_id},
    )


# --- Daily reminders --------------------------------------------------------------------------------

_DUE = text(
    """
    select s.id, s.plan_id, s.seq, s.due_date, s.remaining, sa.sale_no, c.name as customer_name, c.phone_primary
      from public.installment_status s
      join public.sales sa on sa.id = s.sale_id
      join public.customers c on c.id = s.customer_id
     where s.plan_status = 'ACTIVE' and s.remaining > 0 and s.due_date <= :until
     order by s.due_date
    """
)


def run_reminders(conn: Connection, today: date, sms: MessageProvider) -> dict[str, int] | None:
    """Create today's reminders for the current tenant: installments due within
    the configured window (default 2 days) and overdue ones. Runs once per tenant
    per day (reminder_jobs); returns None when today's run already happened."""
    started = conn.execute(
        text(
            """
            insert into public.reminder_jobs (tenant_id, job_name, run_date)
            values (private.current_tenant_id(), 'installment_reminders', :today)
            on conflict (tenant_id, job_name, run_date) do nothing
            returning id
            """
        ),
        {"today": today},
    ).scalar_one_or_none()
    if started is None:
        return None
    days = conn.execute(
        text("select coalesce((attention_thresholds ->> 'installment_due_days')::int, 2) from public.tenant_settings")
    ).scalar_one()
    stats = {"due_soon": 0, "overdue": 0, "notifications": 0}
    for row in conn.execute(_DUE, {"until": today + timedelta(days=days)}).fetchall():
        overdue = row.due_date < today
        params = {
            "customer": row.customer_name,
            "seq": row.seq,
            "sale_no": row.sale_no,
            "due_date": row.due_date.isoformat(),
            "remaining": f"{row.remaining:.2f}",
            "days_late": (today - row.due_date).days if overdue else 0,
            "plan_id": str(row.plan_id),
        }
        # Due-soon: once per installment; overdue: once when it becomes overdue (D-86).
        kind = "INSTALLMENT_OVERDUE" if overdue else "INSTALLMENT_DUE_SOON"
        stats["overdue" if overdue else "due_soon"] += 1
        stats["notifications"] += notify_permission(
            conn,
            permission="installment.view",
            kind=kind,
            params=params,
            entity_type="INSTALLMENT",
            entity_id=row.id,
            dedupe_key=f"{kind}:{row.id}",
        )
        if not overdue and row.phone_primary:
            sms.send(row.phone_primary, "installment_due_soon", {k: str(v) for k, v in params.items()})
    conn.execute(
        text(
            "update public.reminder_jobs set status = 'DONE', finished_at = now(), stats = cast(:stats as jsonb) "
            "where id = :id"
        ),
        {"stats": _json(stats), "id": started},
    )
    return stats
