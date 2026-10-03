"""SaaS layer (SPEC §4.15, §4.16; BACKLOG 9.1-9.5, 9.9).

* Super admin console: every tenant with plan, status and usage; plan and
  status changes; manual invoices marked paid (the PaymentGateway interface
  replaces this later, D-116).
* Support access: a showroom grants a time-boxed window; without an active
  grant the platform sees nothing of its data. Every look is audit-logged.
* Self-serve signup, branches within the plan, the audit log viewer and the
  tenant's full data export.
"""

import io
import json
import zipfile
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import Connection, text
from sqlalchemy.exc import DBAPIError

from app.core.errors import AppError, not_found
from app.domain.platform import (
    AuditPage,
    AuditRow,
    BranchIn,
    BranchOut,
    InvoiceIn,
    InvoiceOut,
    PlatformTenant,
    PlatformTenantUpdate,
    SignupIn,
    SupportGrantIn,
    SupportGrantOut,
    SupportSummary,
    UsageOut,
)
from app.services import plans
from app.services.audit import record_event

# --- Super admin --------------------------------------------------------------------------------------


def is_platform_admin(conn: Connection, user_id: UUID) -> bool:
    return bool(conn.execute(text("select private.user_is_platform_admin(:u)"), {"u": user_id}).scalar_one())


def list_tenants(conn: Connection) -> list[PlatformTenant]:
    return [
        PlatformTenant.model_validate(dict(r))
        for r in conn.execute(text("select * from private.platform_tenants()")).mappings()
    ]


def get_tenant(conn: Connection, tenant_id: UUID) -> PlatformTenant:
    for tenant in list_tenants(conn):
        if tenant.id == tenant_id:
            return tenant
    raise not_found("tenant")


def update_tenant(conn: Connection, tenant_id: UUID, changes: PlatformTenantUpdate, *, actor: UUID) -> PlatformTenant:
    before = get_tenant(conn, tenant_id)
    conn.execute(
        text("select private.platform_update_tenant(:t, :s, :p, :ts, :pe)"),
        {
            "t": tenant_id,
            "s": changes.subscription_status,
            "p": changes.plan_code,
            "ts": changes.tenant_status,
            "pe": changes.current_period_end,
        },
    )
    after = get_tenant(conn, tenant_id)
    record_event(
        conn,
        tenant_id=tenant_id,
        actor=actor,
        action="PLATFORM_TENANT_UPDATED",
        entity_type="tenants",
        entity_id=str(tenant_id),
        details={
            "reason": changes.reason,
            "before": {"status": before.subscription_status, "plan": before.plan_code, "tenant": before.tenant_status},
            "after": {"status": after.subscription_status, "plan": after.plan_code, "tenant": after.tenant_status},
        },
        actor_kind="PLATFORM",
    )
    return after


def list_invoices(conn: Connection, tenant_id: UUID) -> list[InvoiceOut]:
    rows = conn.execute(
        text("select * from public.invoices where tenant_id = :t order by period_start desc"), {"t": tenant_id}
    ).mappings()
    return [InvoiceOut.model_validate(dict(r)) for r in rows]


def issue_invoice(conn: Connection, tenant_id: UUID, payload: InvoiceIn, *, actor: UUID) -> InvoiceOut:
    if payload.period_end < payload.period_start:
        raise AppError("DATE_RANGE_INVALID", "The period ends before it starts", status_code=422)
    currency = conn.execute(
        text("select currency_code from public.tenants where id = :t"), {"t": tenant_id}
    ).scalar_one_or_none()
    if currency is None:
        raise not_found("tenant")
    row = (
        conn.execute(
            text(
                """
            insert into public.invoices (tenant_id, period_start, period_end, amount, currency_code)
            values (:t, :s, :e, :a, :c) returning *
            """
            ),
            {"t": tenant_id, "s": payload.period_start, "e": payload.period_end, "a": payload.amount, "c": currency},
        )
        .mappings()
        .one()
    )
    record_event(
        conn,
        tenant_id=tenant_id,
        actor=actor,
        action="INVOICE_ISSUED",
        entity_type="invoices",
        entity_id=str(row["id"]),
        details={"amount": f"{payload.amount:.2f}"},
        actor_kind="PLATFORM",
    )
    return InvoiceOut.model_validate(dict(row))


def mark_paid(conn: Connection, invoice_id: UUID, reference: str | None, *, actor: UUID) -> InvoiceOut:
    """Manual billing (SPEC §4.16): paying an invoice reactivates the subscription to the period's end."""
    row = (
        conn.execute(
            text(
                "update public.invoices set status = 'PAID', paid_at = now(), reference = :r, marked_by = :u "
                "where id = :id and status = 'ISSUED' returning *"
            ),
            {"r": reference, "u": actor, "id": invoice_id},
        )
        .mappings()
        .first()
    )
    if row is None:
        raise AppError("INVOICE_NOT_OPEN", "Only an issued invoice can be marked paid", status_code=409)
    period_end = datetime.combine(row["period_end"], datetime.max.time()).astimezone()
    conn.execute(
        text("select private.platform_update_tenant(:t, 'ACTIVE', null, null, :pe)"),
        {"t": row["tenant_id"], "pe": period_end},
    )
    record_event(
        conn,
        tenant_id=row["tenant_id"],
        actor=actor,
        action="INVOICE_PAID",
        entity_type="invoices",
        entity_id=str(invoice_id),
        details={"reference": reference},
        actor_kind="PLATFORM",
    )
    return InvoiceOut.model_validate(dict(row))


def support_summary(conn: Connection, tenant_id: UUID, *, actor: UUID) -> SupportSummary:
    """Read-only view inside a showroom; refused without an active grant (D-117)."""
    grant = conn.execute(
        text(
            "select max(expires_at) from public.support_grants where tenant_id = :t and revoked_at is null "
            "and now() between starts_at and expires_at"
        ),
        {"t": tenant_id},
    ).scalar_one()
    if grant is None:
        raise AppError("SUPPORT_NOT_GRANTED", "The showroom has not granted support access", status_code=403)
    tenant = get_tenant(conn, tenant_id)
    counts = {
        name: int(conn.execute(text(sql), {"t": tenant_id}).scalar_one())
        for name, sql in {
            "vehicles": "select count(*) from public.vehicles where tenant_id = :t",
            "customers": "select count(*) from public.customers where tenant_id = :t",
            "sales": "select count(*) from public.sales where tenant_id = :t and status = 'POSTED'",
            "journal_entries": "select count(*) from public.journal_entries where tenant_id = :t",
            "open_plans": "select count(*) from public.installment_plans where tenant_id = :t and status = 'ACTIVE'",
        }.items()
    }
    by_status = {
        r.status: int(r.n)
        for r in conn.execute(
            text("select status, count(*) as n from public.vehicles where tenant_id = :t group by status"),
            {"t": tenant_id},
        )
    }
    events = [
        {"occurred_at": r.occurred_at.isoformat(), "action": r.action, "entity_type": r.entity_type}
        for r in conn.execute(
            text(
                "select occurred_at, action, entity_type from public.audit_log where tenant_id = :t "
                "order by occurred_at desc limit 20"
            ),
            {"t": tenant_id},
        )
    ]
    record_event(
        conn,
        tenant_id=tenant_id,
        actor=actor,
        action="SUPPORT_VIEW",
        entity_type="tenants",
        entity_id=str(tenant_id),
        actor_kind="PLATFORM",
    )
    return SupportSummary(
        tenant_id=tenant_id,
        name_ar=tenant.name_ar,
        subscription_status=tenant.subscription_status,
        granted_until=grant,
        counts=counts,
        vehicles_by_status=by_status,
        recent_events=events,
    )


# --- Tenant side --------------------------------------------------------------------------------------

_GRANTS = """
    select g.id, g.reason, g.starts_at, g.expires_at, g.revoked_at,
           (g.revoked_at is null and now() between g.starts_at and g.expires_at) as active,
           coalesce(u.full_name, u.email) as granted_by_name
      from public.support_grants g
      left join private.tenant_members() u on u.user_id = g.granted_by
"""


def list_grants(conn: Connection) -> list[SupportGrantOut]:
    rows = conn.execute(
        text(_GRANTS + " where g.tenant_id = private.current_tenant_id() order by g.created_at desc limit 20")
    ).mappings()
    return [SupportGrantOut.model_validate(dict(r)) for r in rows]


def grant_support(conn: Connection, payload: SupportGrantIn, *, actor: UUID, tenant_id: UUID) -> SupportGrantOut:
    grant_id = conn.execute(
        text(
            "insert into public.support_grants (tenant_id, granted_by, reason, expires_at) "
            "values (:t, :u, :r, now() + make_interval(hours => :h)) returning id"
        ),
        {"t": tenant_id, "u": actor, "r": payload.reason, "h": payload.hours},
    ).scalar_one()
    record_event(
        conn,
        tenant_id=tenant_id,
        actor=actor,
        action="SUPPORT_GRANTED",
        entity_type="support_grants",
        entity_id=str(grant_id),
        details={"hours": payload.hours, "reason": payload.reason},
    )
    return next(g for g in list_grants(conn) if g.id == grant_id)


def revoke_support(conn: Connection, grant_id: UUID, *, actor: UUID, tenant_id: UUID) -> SupportGrantOut:
    updated = conn.execute(
        text(
            "update public.support_grants set revoked_at = now() where id = :id and tenant_id = :t "
            "and revoked_at is null returning id"
        ),
        {"id": grant_id, "t": tenant_id},
    ).first()
    if updated is None:
        raise not_found("support grant")
    record_event(
        conn,
        tenant_id=tenant_id,
        actor=actor,
        action="SUPPORT_REVOKED",
        entity_type="support_grants",
        entity_id=str(grant_id),
    )
    return next(g for g in list_grants(conn) if g.id == grant_id)


def signup(conn: Connection, payload: SignupIn, *, user_id: UUID) -> UUID:
    """A signed-in user creates a showroom on the trial plan and owns it (D-118)."""
    owned = conn.execute(text("select count(*) from private.user_owned_tenants(:u)"), {"u": user_id}).scalar_one()
    if owned >= 3:
        raise AppError("SIGNUP_LIMIT", "You already own three showrooms; contact us to add more", status_code=409)
    tenant_id: UUID = conn.execute(
        text("select private.create_tenant(:u, :ar, :en, :c)"),
        {"u": user_id, "ar": payload.name_ar, "en": payload.name_en, "c": payload.country_code},
    ).scalar_one()
    # The new showroom is the request's tenant from here on (audit row, RLS).
    conn.execute(text("select set_config('app.tenant_id', :t, true)"), {"t": str(tenant_id)})
    record_event(
        conn,
        tenant_id=tenant_id,
        actor=user_id,
        action="TENANT_SIGNUP",
        entity_type="tenants",
        entity_id=str(tenant_id),
        details={"country": payload.country_code},
    )
    return tenant_id


def list_branches(conn: Connection) -> list[BranchOut]:
    rows = conn.execute(
        text(
            "select id, name_ar, name_en, address, is_default from public.branches where archived_at is null "
            "order by is_default desc, created_at"
        )
    ).mappings()
    return [BranchOut.model_validate(dict(r)) for r in rows]


def create_branch(conn: Connection, payload: BranchIn) -> BranchOut:
    if plans.usage(conn, "branches") >= 1:
        plans.ensure_feature(conn, "multi_branch")
    plans.ensure_room(conn, "branches")
    branch_id = conn.execute(
        text(
            "insert into public.branches (tenant_id, name_ar, name_en, address) "
            "values (private.current_tenant_id(), :name_ar, :name_en, :address) returning id"
        ),
        payload.model_dump(),
    ).scalar_one()
    return next(b for b in list_branches(conn) if b.id == branch_id)


def usage(conn: Connection) -> UsageOut:
    plan = conn.execute(
        text(
            "select p.code, p.limits from public.subscriptions s join public.plans p on p.id = s.plan_id "
            "where s.tenant_id = private.current_tenant_id()"
        )
    ).first()
    limits = {k: int(v) for k, v in (plan.limits if plan else {}).items()}
    return UsageOut(
        plan_code=plan.code if plan else None,
        limits=limits,
        used={key: plans.usage(conn, key) for key in ("users", "branches", "vehicles_in_stock")},
    )


def audit_page(
    conn: Connection,
    *,
    entity_type: str | None,
    action: str | None,
    actor: UUID | None,
    date_from: date | None,
    date_to: date | None,
    page: int,
    page_size: int,
) -> AuditPage:
    where = """
     where a.tenant_id = private.current_tenant_id()
       and (cast(:entity as text) is null or a.entity_type = :entity)
       and (cast(:action as text) is null or a.action ilike '%' || :action || '%')
       and (cast(:actor as uuid) is null or a.actor_user_id = :actor)
       and (cast(:f as date) is null or a.occurred_at >= cast(:f as date))
       and (cast(:t as date) is null or a.occurred_at < cast(:t as date) + 1)
    """
    params = {"entity": entity_type, "action": action, "actor": actor, "f": date_from, "t": date_to}
    total = conn.execute(text("select count(*) from public.audit_log a" + where), params).scalar_one()  # noqa: S608
    rows = conn.execute(
        text(
            "select a.id, a.occurred_at, a.actor_user_id, coalesce(m.full_name, m.email) as actor_name, a.actor_kind, "
            "a.action, a.entity_type, a.entity_id, a.before, a.after, a.details, host(a.ip) as ip "
            "from public.audit_log a left join private.tenant_members() m on m.user_id = a.actor_user_id"
            + where
            + " order by a.occurred_at desc, a.id desc limit :limit offset :offset"
        ),
        {**params, "limit": page_size, "offset": (page - 1) * page_size},
    ).mappings()
    return AuditPage(
        items=[AuditRow.model_validate(dict(r)) for r in rows], page=page, page_size=page_size, total=total
    )


# --- Data export (9.9) ----------------------------------------------------------------------------------

_SKIP = {"idempotency_keys"}


def _tenant_tables(conn: Connection) -> list[str]:
    return list(
        conn.execute(
            text(
                """
                select c.table_name from information_schema.columns c
                  join information_schema.tables t on t.table_schema = c.table_schema and t.table_name = c.table_name
                 where c.table_schema = 'public' and c.column_name = 'tenant_id' and t.table_type = 'BASE TABLE'
                 order by c.table_name
                """
            )
        ).scalars()
    )


def _jsonable(value: Any) -> Any:
    if isinstance(value, Decimal):
        return f"{value}"
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    return value


def export_zip(conn: Connection, *, actor: UUID | None, tenant_id: UUID) -> bytes:
    """Every row of every table of the showroom as JSON, one file per table (never cost-filtered:
    only the owner may download it). National IDs stay encrypted."""
    buffer = io.BytesIO()
    counts: dict[str, int] = {}
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for table in _tenant_tables(conn):
            if table in _SKIP:
                continue
            try:
                with conn.begin_nested():
                    rows = (
                        conn.execute(
                            text(f"select * from public.{table} where tenant_id = :t"),  # noqa: S608 - names from the catalogue
                            {"t": tenant_id},
                        )
                        .mappings()
                        .all()
                    )
            except DBAPIError:
                continue  # a table the API role cannot read (none expected) is left out
            counts[table] = len(rows)
            payload = [{k: _jsonable(v) for k, v in row.items()} for row in rows]
            archive.writestr(f"{table}.json", json.dumps(payload, ensure_ascii=False, indent=1))
        archive.writestr(
            "manifest.json",
            json.dumps(
                {"tenant_id": str(tenant_id), "exported_at": datetime.now().astimezone().isoformat(), "tables": counts},
                ensure_ascii=False,
                indent=1,
            ),
        )
    record_event(
        conn,
        tenant_id=tenant_id,
        actor=actor,
        action="TENANT_EXPORTED",
        entity_type="tenants",
        entity_id=str(tenant_id),
        details={"tables": len(counts)},
    )
    return buffer.getvalue()


def nightly_export(conn: Connection, tenant_id: UUID, today: date, directory: str, keep_days: int) -> str | None:
    """Once a day per tenant (BACKLOG 9.9): the full export as a zip under
    <directory>/<tenant>/<date>.zip; files older than `keep_days` are removed."""
    started = conn.execute(
        text(
            "insert into public.reminder_jobs (tenant_id, job_name, run_date) "
            "values (:t, 'tenant_export', :d) on conflict (tenant_id, job_name, run_date) do nothing returning id"
        ),
        {"t": tenant_id, "d": today},
    ).scalar_one_or_none()
    if started is None:
        return None
    folder = Path(directory) / str(tenant_id)
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / f"{today.isoformat()}.zip"
    target.write_bytes(export_zip(conn, actor=None, tenant_id=tenant_id))
    for old in folder.glob("*.zip"):
        try:
            if date.fromisoformat(old.stem) < today - timedelta(days=keep_days):
                old.unlink()
        except ValueError:
            continue
    conn.execute(
        text("update public.reminder_jobs set status = 'DONE', finished_at = now() where id = :id"), {"id": started}
    )
    return str(target)
