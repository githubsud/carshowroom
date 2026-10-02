"""Reservations and sales (docs/API.md §3.6). Sale profit is shown only with
vehicle.view_cost; sales staff see posted sales and their own drafts."""

from contextlib import AbstractContextManager
from datetime import date
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query
from fastapi.responses import JSONResponse, Response
from sqlalchemy import Connection, text

from app.api.deps import TenantContext, get_database, get_storage, require, require_any, require_writable
from app.api.masking import masked
from app.db.session import Database
from app.domain.finance import PostingResult, Preview
from app.domain.permissions import Permission
from app.domain.sales import (
    ReservationIn,
    ReservationOut,
    ReservationSettleIn,
    ReservationStatus,
    SaleCancelIn,
    SaleDraftIn,
    SaleOut,
    SalePage,
    SaleStatus,
)
from app.integrations.storage import Storage
from app.reports import sale_documents
from app.services import idempotency, sales

router = APIRouter(tags=["sales"])

IdempotencyKey = Annotated[str | None, Header(alias="Idempotency-Key")]


def _tx(db: Database, ctx: TenantContext) -> AbstractContextManager[Connection]:
    return db.transaction(user_id=ctx.user.id, tenant_id=ctx.tenant_id)


def _with_profit(ctx: TenantContext) -> bool:
    return ctx.can(Permission.VEHICLE_VIEW_COST)


def _see_all_drafts(ctx: TenantContext) -> bool:
    return ctx.can(Permission.SALE_POST)


# --- Reservations (rules 11, 34, 35) ------------------------------------------------------------------


@router.get("/reservations", response_model=list[ReservationOut])
def list_reservations(
    status: ReservationStatus | None = None,
    vehicle_id: UUID | None = None,
    ctx: TenantContext = Depends(require_any(Permission.SALE_VIEW, Permission.RESERVATION_MANAGE)),
    db: Database = Depends(get_database),
) -> list[ReservationOut]:
    with _tx(db, ctx) as conn:
        return sales.list_reservations(conn, status=status, vehicle_id=vehicle_id)


@router.post("/reservations/preview", response_model=Preview)
def preview_reservation(
    payload: ReservationIn,
    ctx: TenantContext = Depends(require(Permission.RESERVATION_MANAGE)),
    db: Database = Depends(get_database),
) -> Preview:
    with _tx(db, ctx) as conn:
        return sales.preview_reservation(conn, payload, with_lines=ctx.can(Permission.JOURNAL_VIEW))


@router.post("/reservations", response_model=PostingResult[ReservationOut], status_code=201)
def create_reservation(
    payload: ReservationIn,
    idempotency_key: IdempotencyKey = None,
    ctx: TenantContext = Depends(require(Permission.RESERVATION_MANAGE)),
    db: Database = Depends(get_database),
) -> JSONResponse:
    require_writable(ctx)
    return idempotency.run(
        db,
        user_id=ctx.user.id,
        tenant_id=ctx.tenant_id,
        key=idempotency_key,
        endpoint="POST /reservations",
        payload=payload,
        operation=lambda conn: sales.create_reservation(conn, payload),
    )


@router.post("/reservations/{reservation_id}/settle/preview", response_model=Preview)
def preview_settle(
    reservation_id: UUID,
    payload: ReservationSettleIn,
    ctx: TenantContext = Depends(require(Permission.RESERVATION_MANAGE)),
    db: Database = Depends(get_database),
) -> Preview:
    with _tx(db, ctx) as conn:
        return sales.preview_settle(conn, reservation_id, payload, with_lines=ctx.can(Permission.JOURNAL_VIEW))


@router.post("/reservations/{reservation_id}/settle", response_model=PostingResult[ReservationOut], status_code=201)
def settle_reservation(
    reservation_id: UUID,
    payload: ReservationSettleIn,
    idempotency_key: IdempotencyKey = None,
    ctx: TenantContext = Depends(require(Permission.RESERVATION_MANAGE)),
    db: Database = Depends(get_database),
) -> JSONResponse:
    require_writable(ctx)
    return idempotency.run(
        db,
        user_id=ctx.user.id,
        tenant_id=ctx.tenant_id,
        key=idempotency_key,
        endpoint=f"POST /reservations/{reservation_id}/settle",
        payload=payload,
        operation=lambda conn: sales.settle_reservation(conn, reservation_id, payload),
    )


# --- Sales ------------------------------------------------------------------------------------------------


@router.get("/sales", response_model=SalePage)
def list_sales(
    status: SaleStatus | None = None,
    q: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 25,
    ctx: TenantContext = Depends(require(Permission.SALE_VIEW)),
    db: Database = Depends(get_database),
) -> SalePage:
    with _tx(db, ctx) as conn:
        return sales.list_sales(
            conn,
            status=status,
            q=q,
            date_from=date_from,
            date_to=date_to,
            viewer_id=ctx.user.id,
            see_all_drafts=_see_all_drafts(ctx),
            page=page,
            page_size=page_size,
        )


@router.post("/sales", response_model=SaleOut, status_code=201)
def create_sale(
    payload: SaleDraftIn,
    ctx: TenantContext = Depends(require(Permission.SALE_DRAFT)),
    db: Database = Depends(get_database),
) -> JSONResponse:
    require_writable(ctx)
    with _tx(db, ctx) as conn:
        sale = sales.create_draft(
            conn,
            payload,
            viewer_id=ctx.user.id,
            see_all_drafts=_see_all_drafts(ctx),
            with_profit=_with_profit(ctx),
        )
    return masked(sale, ctx, status_code=201)


@router.get("/sales/{sale_id}", response_model=SaleOut)
def get_sale(
    sale_id: UUID,
    ctx: TenantContext = Depends(require(Permission.SALE_VIEW)),
    db: Database = Depends(get_database),
) -> JSONResponse:
    with _tx(db, ctx) as conn:
        sale = sales.get_sale(
            conn, sale_id, viewer_id=ctx.user.id, see_all_drafts=_see_all_drafts(ctx), with_profit=_with_profit(ctx)
        )
    return masked(sale, ctx)


@router.put("/sales/{sale_id}", response_model=SaleOut)
def update_sale(
    sale_id: UUID,
    payload: SaleDraftIn,
    ctx: TenantContext = Depends(require(Permission.SALE_DRAFT)),
    db: Database = Depends(get_database),
) -> JSONResponse:
    require_writable(ctx)
    with _tx(db, ctx) as conn:
        sale = sales.update_draft(
            conn,
            sale_id,
            payload,
            viewer_id=ctx.user.id,
            can_edit_others=_see_all_drafts(ctx),
            with_profit=_with_profit(ctx),
        )
    return masked(sale, ctx)


@router.delete("/sales/{sale_id}", status_code=204)
def delete_sale(
    sale_id: UUID,
    ctx: TenantContext = Depends(require(Permission.SALE_DRAFT)),
    db: Database = Depends(get_database),
) -> Response:
    require_writable(ctx)
    with _tx(db, ctx) as conn:
        sales.delete_draft(conn, sale_id, viewer_id=ctx.user.id, can_edit_others=_see_all_drafts(ctx))
    return Response(status_code=204)


@router.post("/sales/{sale_id}/post/preview", response_model=Preview)
def preview_post(
    sale_id: UUID,
    ctx: TenantContext = Depends(require(Permission.SALE_POST)),
    db: Database = Depends(get_database),
) -> Preview:
    with _tx(db, ctx) as conn:
        return sales.preview_post(
            conn, sale_id, with_lines=ctx.can(Permission.JOURNAL_VIEW), with_profit=_with_profit(ctx)
        )


@router.post("/sales/{sale_id}/post", response_model=PostingResult[SaleOut], status_code=201)
def post_sale(
    sale_id: UUID,
    idempotency_key: IdempotencyKey = None,
    ctx: TenantContext = Depends(require(Permission.SALE_POST)),
    db: Database = Depends(get_database),
) -> JSONResponse:
    require_writable(ctx)
    return idempotency.run(
        db,
        user_id=ctx.user.id,
        tenant_id=ctx.tenant_id,
        key=idempotency_key,
        endpoint=f"POST /sales/{sale_id}/post",
        payload=None,
        operation=lambda conn: sales.post_sale(conn, sale_id, user_id=ctx.user.id, with_profit=_with_profit(ctx)),
    )


@router.post("/sales/{sale_id}/cancel/preview", response_model=Preview)
def preview_cancel(
    sale_id: UUID,
    payload: SaleCancelIn,
    ctx: TenantContext = Depends(require(Permission.SALE_CANCEL)),
    db: Database = Depends(get_database),
) -> Preview:
    with _tx(db, ctx) as conn:
        return sales.preview_cancel(conn, sale_id, payload, with_lines=ctx.can(Permission.JOURNAL_VIEW))


@router.post("/sales/{sale_id}/cancel", response_model=PostingResult[SaleOut], status_code=201)
def cancel_sale(
    sale_id: UUID,
    payload: SaleCancelIn,
    idempotency_key: IdempotencyKey = None,
    ctx: TenantContext = Depends(require(Permission.SALE_CANCEL)),
    db: Database = Depends(get_database),
) -> JSONResponse:
    require_writable(ctx)
    return idempotency.run(
        db,
        user_id=ctx.user.id,
        tenant_id=ctx.tenant_id,
        key=idempotency_key,
        endpoint=f"POST /sales/{sale_id}/cancel",
        payload=payload,
        operation=lambda conn: sales.cancel_sale(
            conn, sale_id, payload, user_id=ctx.user.id, with_profit=_with_profit(ctx)
        ),
    )


@router.get(
    "/sales/{sale_id}/document",
    responses={200: {"content": {"application/pdf": {}}}},
    response_class=Response,
)
def sale_document(
    sale_id: UUID,
    kind: Literal["invoice", "contract"] = "invoice",
    lang: Literal["ar", "en"] = "ar",
    ctx: TenantContext = Depends(require(Permission.SALE_VIEW)),
    db: Database = Depends(get_database),
    storage: Storage = Depends(get_storage),
) -> Response:
    with _tx(db, ctx) as conn:
        context = sales.document_context(conn, sale_id)
        logo_path = conn.execute(
            text("select logo_path from public.tenants where id = private.current_tenant_id()")
        ).scalar_one()
    logo_url = storage.view_urls("documents", [logo_path]).get(logo_path) if logo_path else None
    content = sale_documents.render_pdf(context, kind, lang, logo_url)
    return Response(
        content,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{sale_documents.filename(context, kind)}"'},
    )
