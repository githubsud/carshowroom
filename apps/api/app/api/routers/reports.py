"""Reports centre and dashboard (docs/API.md §3.10).

Every report is served as JSON (a ``ReportTable``), PDF or Excel from the same
numbers. Each report has its own permission; cost and profit reports need
vehicle.view_cost, so sales staff never receive them.
"""

from contextlib import AbstractContextManager
from datetime import date
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends
from fastapi.responses import Response
from sqlalchemy import Connection, text

from app.api.deps import TenantContext, get_database, require, require_any
from app.core.errors import AppError
from app.db.session import Database
from app.domain.dashboard import AttentionItem, DashboardOut
from app.domain.permissions import Permission
from app.domain.reports import ReportFilters, ReportFormat, ReportName, ReportTable
from app.reports import tabular
from app.services import attention, dashboard, reports

router = APIRouter(tags=["reports"])

_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

# Which permission each report needs (SPEC §4.12, ARCHITECTURE §7).
REPORT_PERMISSIONS: dict[ReportName, Permission] = {
    "profit-and-loss": Permission.REPORT_FINANCIAL,
    "trial-balance": Permission.JOURNAL_VIEW,
    "general-ledger": Permission.JOURNAL_VIEW,
    "balance-check": Permission.REPORT_FINANCIAL,
    "vehicle-profit": Permission.VEHICLE_VIEW_COST,
    "inventory-aging": Permission.VEHICLE_VIEW_COST,
    "expenses-by-category": Permission.REPORT_FINANCIAL,
    "installment-collections": Permission.INSTALLMENT_VIEW,
    "deferred-papers": Permission.DEFERRED_PAPER_MANAGE,
    "consignments-in": Permission.CONSIGNMENT_SETTLE,
    "consignments-out": Permission.CONSIGNMENT_MANAGE,
}


def _tx(db: Database, ctx: TenantContext) -> AbstractContextManager[Connection]:
    return db.transaction(user_id=ctx.user.id, tenant_id=ctx.tenant_id)


@router.get("/reports", response_model=list[ReportName])
def available_reports(
    ctx: TenantContext = Depends(require(Permission.DASHBOARD_VIEW)),
) -> list[ReportName]:
    """The reports this user may open, in the order of the reports centre."""
    return [name for name, permission in REPORT_PERMISSIONS.items() if ctx.can(permission)]


@router.get(
    "/reports/{name}",
    response_model=ReportTable,
    responses={200: {"content": {"application/pdf": {}, _XLSX: {}}}},
)
def run_report(
    name: ReportName,
    date_from: date | None = None,
    date_to: date | None = None,
    as_of: date | None = None,
    account_id: UUID | None = None,
    format: ReportFormat = "json",
    lang: Literal["ar", "en"] = "ar",
    ctx: TenantContext = Depends(require(Permission.DASHBOARD_VIEW)),
    db: Database = Depends(get_database),
) -> ReportTable | Response:
    if not ctx.can(REPORT_PERMISSIONS[name]):
        raise AppError("PERMISSION_DENIED", "You do not have access to this report", status_code=403)
    filters = ReportFilters(date_from=date_from, date_to=date_to, as_of=as_of, account_id=account_id)
    with _tx(db, ctx) as conn:
        table = reports.BUILDERS[name](conn, filters)
        showroom = conn.execute(
            text("select name_ar, coalesce(name_en, name_ar) as name_en from public.tenants where id = :id"),
            {"id": ctx.tenant_id},
        ).one()
    if format == "json":
        return table
    if format == "xlsx":
        content, media_type = tabular.render_xlsx(table, lang), _XLSX
    else:
        name_text = showroom.name_ar if lang == "ar" else showroom.name_en
        content, media_type = tabular.render_pdf(table, lang, name_text), "application/pdf"
    return Response(
        content,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{tabular.filename(table, format)}"'},
    )


@router.get("/dashboard", response_model=DashboardOut, tags=["dashboard"])
def get_dashboard(
    ctx: TenantContext = Depends(require_any(Permission.DASHBOARD_VIEW)),
    db: Database = Depends(get_database),
) -> DashboardOut:
    with _tx(db, ctx) as conn:
        enabled = conn.execute(
            text("select private.feature_enabled(private.current_tenant_id(), 'installments')")
        ).scalar_one()
        return dashboard.build(conn, ctx.can, installments_enabled=bool(enabled))


@router.get("/attention", response_model=list[AttentionItem], tags=["dashboard"])
def needs_attention(
    ctx: TenantContext = Depends(require_any(Permission.DASHBOARD_VIEW)),
    db: Database = Depends(get_database),
) -> list[AttentionItem]:
    with _tx(db, ctx) as conn:
        return attention.alerts(conn, ctx.can)
