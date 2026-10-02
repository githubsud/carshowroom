"""Installments, receipts, deferred papers and notifications (docs/API.md §3.7, §3.12)."""

from contextlib import AbstractContextManager
from datetime import date
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query
from fastapi.responses import JSONResponse, Response
from sqlalchemy import Connection, text

from app.api.deps import TenantContext, get_database, require, require_writable
from app.db.session import Database
from app.domain.finance import PostingResult, Preview
from app.domain.installments import (
    CustomerInstallmentStatement,
    InstallmentBoard,
    InstallmentKpis,
    InstallmentOut,
    InstallmentPlanOut,
    NotificationPage,
    PaperActionIn,
    PaperIn,
    PaperOut,
    PaperStatus,
    PaperType,
    ReceiptIn,
    SchedulePreviewIn,
    ScheduleRowOut,
)
from app.domain.permissions import Permission
from app.reports import installment_statement
from app.services import idempotency, installments, notifications, papers

router = APIRouter(tags=["installments"])

IdempotencyKey = Annotated[str | None, Header(alias="Idempotency-Key")]
View = Literal["open", "due_today", "upcoming", "overdue", "calendar"]


def _tx(db: Database, ctx: TenantContext) -> AbstractContextManager[Connection]:
    return db.transaction(user_id=ctx.user.id, tenant_id=ctx.tenant_id)


@router.post("/installment-plans/schedule-preview", response_model=list[ScheduleRowOut])
def schedule_preview(
    payload: SchedulePreviewIn, ctx: TenantContext = Depends(require(Permission.SALE_DRAFT))
) -> list[ScheduleRowOut]:
    return installments.preview_schedule(payload.financed, payload.plan)


@router.get("/installments", response_model=list[InstallmentOut])
def list_installments(
    view: View = "open",
    days: Annotated[int, Query(ge=0, le=365)] = 7,
    customer_id: UUID | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    ctx: TenantContext = Depends(require(Permission.INSTALLMENT_VIEW)),
    db: Database = Depends(get_database),
) -> list[InstallmentOut]:
    with _tx(db, ctx) as conn:
        return installments.list_installments(
            conn, view=view, days=days, customer_id=customer_id, date_from=date_from, date_to=date_to
        )


@router.get("/installments/board", response_model=InstallmentBoard)
def installment_board(
    view: View = "open",
    days: Annotated[int, Query(ge=0, le=365)] = 7,
    customer_id: UUID | None = None,
    ctx: TenantContext = Depends(require(Permission.INSTALLMENT_VIEW)),
    db: Database = Depends(get_database),
) -> InstallmentBoard:
    with _tx(db, ctx) as conn:
        return installments.board(conn, view=view, days=days, customer_id=customer_id)


@router.get("/installments/kpis", response_model=InstallmentKpis)
def installment_kpis(
    ctx: TenantContext = Depends(require(Permission.INSTALLMENT_VIEW)), db: Database = Depends(get_database)
) -> InstallmentKpis:
    with _tx(db, ctx) as conn:
        return installments.kpis(conn)


@router.get("/installment-plans/{plan_id}", response_model=InstallmentPlanOut)
def get_plan(
    plan_id: UUID,
    ctx: TenantContext = Depends(require(Permission.INSTALLMENT_VIEW)),
    db: Database = Depends(get_database),
) -> InstallmentPlanOut:
    with _tx(db, ctx) as conn:
        return installments.get_plan(conn, plan_id, with_papers=ctx.can(Permission.DEFERRED_PAPER_MANAGE))


@router.post("/installment-plans/{plan_id}/receipts/preview", response_model=Preview)
def preview_receipt(
    plan_id: UUID,
    payload: ReceiptIn,
    ctx: TenantContext = Depends(require(Permission.INSTALLMENT_COLLECT)),
    db: Database = Depends(get_database),
) -> Preview:
    with _tx(db, ctx) as conn:
        return installments.preview_receipt(conn, plan_id, payload, with_lines=ctx.can(Permission.JOURNAL_VIEW))


@router.post("/installment-plans/{plan_id}/receipts", response_model=PostingResult[InstallmentPlanOut], status_code=201)
def record_receipt(
    plan_id: UUID,
    payload: ReceiptIn,
    idempotency_key: IdempotencyKey = None,
    ctx: TenantContext = Depends(require(Permission.INSTALLMENT_COLLECT)),
    db: Database = Depends(get_database),
) -> JSONResponse:
    require_writable(ctx)
    return idempotency.run(
        db,
        user_id=ctx.user.id,
        tenant_id=ctx.tenant_id,
        key=idempotency_key,
        endpoint=f"POST /installment-plans/{plan_id}/receipts",
        payload=payload,
        operation=lambda conn: installments.record_receipt(conn, plan_id, payload),
    )


@router.get(
    "/customers/{customer_id}/installment-statement",
    response_model=CustomerInstallmentStatement,
    responses={200: {"content": {"application/pdf": {}}}},
)
def customer_statement(
    customer_id: UUID,
    format: Literal["json", "pdf"] = "json",
    lang: Literal["ar", "en"] = "ar",
    ctx: TenantContext = Depends(require(Permission.INSTALLMENT_VIEW)),
    db: Database = Depends(get_database),
) -> CustomerInstallmentStatement | Response:
    with _tx(db, ctx) as conn:
        statement = installments.customer_statement(conn, customer_id)
        showroom = conn.execute(
            text("select name_ar, coalesce(name_en, name_ar) as name_en from public.tenants where id = :id"),
            {"id": ctx.tenant_id},
        ).one()
    if format == "json":
        return statement
    content = installment_statement.render_pdf(statement, lang, showroom.name_ar if lang == "ar" else showroom.name_en)
    return Response(
        content,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{installment_statement.filename(statement)}"'},
    )


# --- Deferred papers ----------------------------------------------------------------------------------


@router.get("/deferred-papers", response_model=list[PaperOut], tags=["deferred papers"])
def list_papers(
    status: PaperStatus | None = None,
    paper_type: PaperType | None = None,
    customer_id: UUID | None = None,
    overdue: bool = False,
    ctx: TenantContext = Depends(require(Permission.DEFERRED_PAPER_MANAGE)),
    db: Database = Depends(get_database),
) -> list[PaperOut]:
    with _tx(db, ctx) as conn:
        return papers.list_papers(
            conn, status=status, paper_type=paper_type, customer_id=customer_id, overdue_only=overdue
        )


@router.post("/deferred-papers", response_model=PaperOut, status_code=201, tags=["deferred papers"])
def create_paper(
    payload: PaperIn,
    ctx: TenantContext = Depends(require(Permission.DEFERRED_PAPER_MANAGE)),
    db: Database = Depends(get_database),
) -> PaperOut:
    require_writable(ctx)
    with _tx(db, ctx) as conn:
        return papers.create_paper(conn, payload)


@router.get("/deferred-papers/{paper_id}", response_model=PaperOut, tags=["deferred papers"])
def get_paper(
    paper_id: UUID,
    ctx: TenantContext = Depends(require(Permission.DEFERRED_PAPER_MANAGE)),
    db: Database = Depends(get_database),
) -> PaperOut:
    with _tx(db, ctx) as conn:
        return papers.get_paper(conn, paper_id)


@router.post("/deferred-papers/{paper_id}/actions/preview", response_model=Preview, tags=["deferred papers"])
def preview_paper_action(
    paper_id: UUID,
    payload: PaperActionIn,
    ctx: TenantContext = Depends(require(Permission.DEFERRED_PAPER_MANAGE)),
    db: Database = Depends(get_database),
) -> Preview:
    with _tx(db, ctx) as conn:
        return papers.preview_action(conn, paper_id, payload, with_lines=ctx.can(Permission.JOURNAL_VIEW))


@router.post(
    "/deferred-papers/{paper_id}/actions",
    response_model=PostingResult[PaperOut],
    status_code=201,
    tags=["deferred papers"],
)
def paper_action(
    paper_id: UUID,
    payload: PaperActionIn,
    idempotency_key: IdempotencyKey = None,
    ctx: TenantContext = Depends(require(Permission.DEFERRED_PAPER_MANAGE)),
    db: Database = Depends(get_database),
) -> JSONResponse:
    require_writable(ctx)
    return idempotency.run(
        db,
        user_id=ctx.user.id,
        tenant_id=ctx.tenant_id,
        key=idempotency_key,
        endpoint=f"POST /deferred-papers/{paper_id}/actions",
        payload=payload,
        operation=lambda conn: papers.act(conn, paper_id, payload),
    )


# --- Notifications -------------------------------------------------------------------------------------


@router.get("/notifications", response_model=NotificationPage, tags=["notifications"])
def list_notifications(
    unread_only: bool = False,
    limit: Annotated[int, Query(ge=1, le=100)] = 30,
    ctx: TenantContext = Depends(require()),
    db: Database = Depends(get_database),
) -> NotificationPage:
    with _tx(db, ctx) as conn:
        return notifications.list_for_user(conn, ctx.user.id, unread_only=unread_only, limit=limit)


@router.post("/notifications/{notification_id}/read", status_code=204, tags=["notifications"])
def read_notification(
    notification_id: UUID, ctx: TenantContext = Depends(require()), db: Database = Depends(get_database)
) -> Response:
    with _tx(db, ctx) as conn:
        notifications.mark_read(conn, ctx.user.id, notification_id)
    return Response(status_code=204)


@router.post("/notifications/read-all", status_code=204, tags=["notifications"])
def read_all_notifications(ctx: TenantContext = Depends(require()), db: Database = Depends(get_database)) -> Response:
    with _tx(db, ctx) as conn:
        notifications.mark_read(conn, ctx.user.id, None)
    return Response(status_code=204)
