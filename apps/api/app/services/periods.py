"""Accounting periods: month lock and unlock (SPEC §4.11).

No posting or reversal may be dated inside a locked month; the database
enforces it (journal trigger), this service only changes the status.
Locking waits for in-flight postings into that month (row lock on the period).
"""

import re
from datetime import date
from uuid import UUID

from sqlalchemy import Connection, text

from app.core.errors import AppError, not_found
from app.domain.finance import PeriodOut
from app.services.audit import record_event

_MONTH = re.compile(r"^(\d{4})-(0[1-9]|1[0-2])$")


def parse_month(value: str) -> date:
    match = _MONTH.match(value)
    if not match:
        raise AppError(
            "VALIDATION_ERROR",
            "Month must look like 2026-10",
            status_code=422,
            details={"fields": {"month": ["pattern"]}},
        )
    return date(int(match.group(1)), int(match.group(2)), 1)


_PERIODS = """
    select to_char(p.month, 'YYYY-MM') as month, p.status, p.locked_at,
           (select count(*) from public.journal_entries e where e.period_id = p.id) as entry_count
      from public.accounting_periods p
"""


def list_periods(conn: Connection) -> list[PeriodOut]:
    rows = conn.execute(text(_PERIODS + " order by p.month desc")).mappings()
    return [PeriodOut.model_validate(dict(row)) for row in rows]


def _get(conn: Connection, month: date) -> PeriodOut:
    row = conn.execute(text(_PERIODS + " where p.month = :month"), {"month": month}).mappings().one()
    return PeriodOut.model_validate(dict(row))


def lock(conn: Connection, *, month: date, actor: UUID, tenant_id: UUID) -> PeriodOut:
    conn.execute(
        text(
            """
            insert into public.accounting_periods (tenant_id, month, status, locked_at, locked_by)
            values (private.current_tenant_id(), :month, 'LOCKED', now(), :actor)
            on conflict (tenant_id, month) do update
               set status = 'LOCKED', locked_at = now(), locked_by = :actor
             where accounting_periods.status = 'OPEN'
            """
        ),
        {"month": month, "actor": actor},
    )
    record_event(
        conn,
        tenant_id=tenant_id,
        actor=actor,
        action="PERIOD_LOCKED",
        entity_type="accounting_periods",
        entity_id=f"{month:%Y-%m}",
    )
    return _get(conn, month)


def unlock(conn: Connection, *, month: date, reason: str, actor: UUID, tenant_id: UUID) -> PeriodOut:
    updated = conn.execute(
        text(
            """
            update public.accounting_periods
               set status = 'OPEN', locked_at = null, locked_by = null
             where month = :month and status = 'LOCKED'
            returning id
            """
        ),
        {"month": month},
    ).first()
    if updated is None:
        if conn.execute(text("select 1 from public.accounting_periods where month = :month"), {"month": month}).first():
            return _get(conn, month)  # already open
        raise not_found("accounting period")
    record_event(
        conn,
        tenant_id=tenant_id,
        actor=actor,
        action="PERIOD_UNLOCKED",
        entity_type="accounting_periods",
        entity_id=f"{month:%Y-%m}",
        details={"reason": reason},
    )
    return _get(conn, month)
