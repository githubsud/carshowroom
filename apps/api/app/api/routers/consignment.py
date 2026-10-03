"""Consignment in and out, external showrooms and their statements (docs/API.md §3.8).

Money with owners and showrooms (balances, settlements, collections,
statements) needs consignment.settle; agreements and moves need
consignment.manage.
"""

from contextlib import AbstractContextManager
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header
from fastapi.responses import JSONResponse, Response
from sqlalchemy import Connection, text

from app.api.deps import TenantContext, get_database, require, require_writable
from app.db.session import Database
from app.domain.consignment import (
    ConsignmentIn,
    ConsignmentInStatus,
    ConsignmentOut,
    ConsignmentOutOut,
    ConsignmentOutStatus,
    ConsignmentReturnIn,
    ConsignmentUpdate,
    ConsignorSettlementIn,
    ConsignorStatement,
    ConsignOutIn,
    ConsignOutReturnIn,
    ExternalCollectionIn,
    ExternalCollectionOut,
    ExternalSaleIn,
    ExternalShowroomIn,
    ExternalShowroomOut,
    ExternalShowroomStatement,
    ExternalShowroomUpdate,
)
from app.domain.finance import PostingResult, Preview
from app.domain.permissions import Permission
from app.reports import consignment_documents
from app.services import consignment, idempotency

router = APIRouter(tags=["consignment"])

IdempotencyKey = Annotated[str | None, Header(alias="Idempotency-Key")]
Format = Literal["json", "pdf"]
Language = Literal["ar", "en"]


def _tx(db: Database, ctx: TenantContext) -> AbstractContextManager[Connection]:
    return db.transaction(user_id=ctx.user.id, tenant_id=ctx.tenant_id)


def _money(ctx: TenantContext) -> bool:
    return ctx.can(Permission.CONSIGNMENT_SETTLE)


def _showroom_name(conn: Connection, ctx: TenantContext, lang: Language) -> str:
    row = conn.execute(
        text("select name_ar, coalesce(name_en, name_ar) as name_en from public.tenants where id = :id"),
        {"id": ctx.tenant_id},
    ).one()
    return str(row.name_ar if lang == "ar" else row.name_en)


def _pdf(html: str, filename: str) -> Response:
    return Response(
        consignment_documents.pdf(html),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# --- External showrooms ----------------------------------------------------------------------------------


@router.get("/external-showrooms", response_model=list[ExternalShowroomOut], tags=["external showrooms"])
def list_showrooms(
    include_archived: bool = False,
    ctx: TenantContext = Depends(require(Permission.CONSIGNMENT_MANAGE)),
    db: Database = Depends(get_database),
) -> list[ExternalShowroomOut]:
    with _tx(db, ctx) as conn:
        return consignment.list_showrooms(conn, include_archived=include_archived, with_balance=_money(ctx))


@router.post("/external-showrooms", response_model=ExternalShowroomOut, status_code=201, tags=["external showrooms"])
def create_showroom(
    payload: ExternalShowroomIn,
    ctx: TenantContext = Depends(require(Permission.CONSIGNMENT_MANAGE)),
    db: Database = Depends(get_database),
) -> ExternalShowroomOut:
    require_writable(ctx)
    with _tx(db, ctx) as conn:
        return consignment.create_showroom(conn, payload)


@router.patch("/external-showrooms/{showroom_id}", response_model=ExternalShowroomOut, tags=["external showrooms"])
def update_showroom(
    showroom_id: UUID,
    changes: ExternalShowroomUpdate,
    ctx: TenantContext = Depends(require(Permission.CONSIGNMENT_MANAGE)),
    db: Database = Depends(get_database),
) -> ExternalShowroomOut:
    require_writable(ctx)
    with _tx(db, ctx) as conn:
        return consignment.update_showroom(conn, showroom_id, changes, with_balance=_money(ctx))


@router.get(
    "/external-showrooms/{showroom_id}/statement",
    response_model=ExternalShowroomStatement,
    responses={200: {"content": {"application/pdf": {}}}},
    tags=["external showrooms"],
)
def showroom_statement(
    showroom_id: UUID,
    format: Format = "json",
    lang: Language = "ar",
    ctx: TenantContext = Depends(require(Permission.CONSIGNMENT_SETTLE)),
    db: Database = Depends(get_database),
) -> ExternalShowroomStatement | Response:
    with _tx(db, ctx) as conn:
        statement = consignment.showroom_statement(conn, showroom_id)
        name = _showroom_name(conn, ctx, lang)
    if format == "json":
        return statement
    return _pdf(
        consignment_documents.showroom_statement_html(statement, lang, name),
        f"showroom-statement-{statement.as_of}.pdf",
    )


@router.post(
    "/external-showrooms/{showroom_id}/collections/preview", response_model=Preview, tags=["external showrooms"]
)
def preview_collection(
    showroom_id: UUID,
    payload: ExternalCollectionIn,
    ctx: TenantContext = Depends(require(Permission.CONSIGNMENT_SETTLE)),
    db: Database = Depends(get_database),
) -> Preview:
    with _tx(db, ctx) as conn:
        return consignment.preview_collection(conn, showroom_id, payload, with_lines=ctx.can(Permission.JOURNAL_VIEW))


@router.post(
    "/external-showrooms/{showroom_id}/collections",
    response_model=PostingResult[ExternalCollectionOut],
    status_code=201,
    tags=["external showrooms"],
)
def record_collection(
    showroom_id: UUID,
    payload: ExternalCollectionIn,
    idempotency_key: IdempotencyKey = None,
    ctx: TenantContext = Depends(require(Permission.CONSIGNMENT_SETTLE)),
    db: Database = Depends(get_database),
) -> JSONResponse:
    require_writable(ctx)
    return idempotency.run(
        db,
        user_id=ctx.user.id,
        tenant_id=ctx.tenant_id,
        key=idempotency_key,
        endpoint=f"POST /external-showrooms/{showroom_id}/collections",
        payload=payload,
        operation=lambda conn: consignment.record_collection(conn, showroom_id, payload),
    )


# --- Consignment IN ------------------------------------------------------------------------------------


@router.get("/consignments", response_model=list[ConsignmentOut])
def list_consignments(
    status: ConsignmentInStatus | None = None,
    consignor_id: UUID | None = None,
    q: str | None = None,
    ctx: TenantContext = Depends(require(Permission.CONSIGNMENT_MANAGE)),
    db: Database = Depends(get_database),
) -> list[ConsignmentOut]:
    with _tx(db, ctx) as conn:
        return consignment.list_consignments(
            conn, status=status, consignor_id=consignor_id, q=q, with_money=_money(ctx)
        )


@router.post("/consignments", response_model=ConsignmentOut, status_code=201)
def create_consignment(
    payload: ConsignmentIn,
    ctx: TenantContext = Depends(require(Permission.CONSIGNMENT_MANAGE)),
    db: Database = Depends(get_database),
) -> ConsignmentOut:
    require_writable(ctx)
    with _tx(db, ctx) as conn:
        return consignment.create_consignment(conn, payload, with_money=_money(ctx))


@router.get("/consignments/{consignment_id}", response_model=ConsignmentOut)
def get_consignment(
    consignment_id: UUID,
    ctx: TenantContext = Depends(require(Permission.CONSIGNMENT_MANAGE)),
    db: Database = Depends(get_database),
) -> ConsignmentOut:
    with _tx(db, ctx) as conn:
        return consignment.get_consignment(conn, consignment_id, with_money=_money(ctx))


@router.put("/consignments/{consignment_id}/terms", response_model=ConsignmentOut)
def update_terms(
    consignment_id: UUID,
    payload: ConsignmentUpdate,
    ctx: TenantContext = Depends(require(Permission.CONSIGNMENT_MANAGE)),
    db: Database = Depends(get_database),
) -> ConsignmentOut:
    require_writable(ctx)
    with _tx(db, ctx) as conn:
        return consignment.update_terms(conn, consignment_id, payload, with_money=_money(ctx))


@router.post("/consignments/{consignment_id}/return", response_model=ConsignmentOut)
def return_to_owner(
    consignment_id: UUID,
    payload: ConsignmentReturnIn,
    ctx: TenantContext = Depends(require(Permission.CONSIGNMENT_MANAGE)),
    db: Database = Depends(get_database),
) -> ConsignmentOut:
    require_writable(ctx)
    with _tx(db, ctx) as conn:
        return consignment.return_to_owner(conn, consignment_id, payload, with_money=_money(ctx))


@router.get(
    "/consignments/{consignment_id}/agreement",
    responses={200: {"content": {"application/pdf": {}}}},
    response_class=Response,
)
def agreement(
    consignment_id: UUID,
    lang: Language = "ar",
    ctx: TenantContext = Depends(require(Permission.CONSIGNMENT_MANAGE)),
    db: Database = Depends(get_database),
) -> Response:
    with _tx(db, ctx) as conn:
        context = consignment.agreement_context(conn, consignment_id)
    return _pdf(
        consignment_documents.agreement_html(context, lang), f"consignment-{context['vehicle']['stock_no']}.pdf"
    )


@router.post("/consignments/{consignment_id}/settlements/preview", response_model=Preview)
def preview_settlement(
    consignment_id: UUID,
    payload: ConsignorSettlementIn,
    ctx: TenantContext = Depends(require(Permission.CONSIGNMENT_SETTLE)),
    db: Database = Depends(get_database),
) -> Preview:
    with _tx(db, ctx) as conn:
        return consignment.preview_settlement(
            conn, consignment_id, payload, with_lines=ctx.can(Permission.JOURNAL_VIEW)
        )


@router.post(
    "/consignments/{consignment_id}/settlements", response_model=PostingResult[ConsignmentOut], status_code=201
)
def record_settlement(
    consignment_id: UUID,
    payload: ConsignorSettlementIn,
    idempotency_key: IdempotencyKey = None,
    ctx: TenantContext = Depends(require(Permission.CONSIGNMENT_SETTLE)),
    db: Database = Depends(get_database),
) -> JSONResponse:
    require_writable(ctx)
    return idempotency.run(
        db,
        user_id=ctx.user.id,
        tenant_id=ctx.tenant_id,
        key=idempotency_key,
        endpoint=f"POST /consignments/{consignment_id}/settlements",
        payload=payload,
        operation=lambda conn: consignment.record_settlement(conn, consignment_id, payload),
    )


@router.get(
    "/customers/{customer_id}/consignor-statement",
    response_model=ConsignorStatement,
    responses={200: {"content": {"application/pdf": {}}}},
)
def consignor_statement(
    customer_id: UUID,
    format: Format = "json",
    lang: Language = "ar",
    ctx: TenantContext = Depends(require(Permission.CONSIGNMENT_SETTLE)),
    db: Database = Depends(get_database),
) -> ConsignorStatement | Response:
    with _tx(db, ctx) as conn:
        statement = consignment.consignor_statement(conn, customer_id)
        name = _showroom_name(conn, ctx, lang)
    if format == "json":
        return statement
    return _pdf(
        consignment_documents.consignor_statement_html(statement, lang, name),
        f"consignor-statement-{statement.as_of}.pdf",
    )


# --- Consignment OUT ------------------------------------------------------------------------------------


@router.get("/consignments-out", response_model=list[ConsignmentOutOut])
def list_out(
    status: ConsignmentOutStatus | None = None,
    external_showroom_id: UUID | None = None,
    ctx: TenantContext = Depends(require(Permission.CONSIGNMENT_MANAGE)),
    db: Database = Depends(get_database),
) -> list[ConsignmentOutOut]:
    with _tx(db, ctx) as conn:
        return consignment.list_out(conn, status=status, showroom_id=external_showroom_id)


@router.post("/consignments-out", response_model=ConsignmentOutOut, status_code=201)
def consign_out(
    payload: ConsignOutIn,
    ctx: TenantContext = Depends(require(Permission.CONSIGNMENT_MANAGE)),
    db: Database = Depends(get_database),
) -> ConsignmentOutOut:
    require_writable(ctx)
    with _tx(db, ctx) as conn:
        return consignment.consign_out(conn, payload)


@router.post("/consignments-out/{out_id}/return", response_model=ConsignmentOutOut)
def return_out(
    out_id: UUID,
    payload: ConsignOutReturnIn,
    ctx: TenantContext = Depends(require(Permission.CONSIGNMENT_MANAGE)),
    db: Database = Depends(get_database),
) -> ConsignmentOutOut:
    require_writable(ctx)
    with _tx(db, ctx) as conn:
        return consignment.return_out(conn, out_id, payload)


@router.post("/consignments-out/{out_id}/sale/preview", response_model=Preview)
def preview_external_sale(
    out_id: UUID,
    payload: ExternalSaleIn,
    ctx: TenantContext = Depends(require(Permission.CONSIGNMENT_SETTLE)),
    db: Database = Depends(get_database),
) -> Preview:
    with _tx(db, ctx) as conn:
        return consignment.preview_external_sale(
            conn,
            out_id,
            payload,
            with_lines=ctx.can(Permission.JOURNAL_VIEW),
            with_profit=ctx.can(Permission.VEHICLE_VIEW_COST),
        )


@router.post("/consignments-out/{out_id}/sale", response_model=PostingResult[ConsignmentOutOut], status_code=201)
def record_external_sale(
    out_id: UUID,
    payload: ExternalSaleIn,
    idempotency_key: IdempotencyKey = None,
    ctx: TenantContext = Depends(require(Permission.CONSIGNMENT_SETTLE)),
    db: Database = Depends(get_database),
) -> JSONResponse:
    require_writable(ctx)
    return idempotency.run(
        db,
        user_id=ctx.user.id,
        tenant_id=ctx.tenant_id,
        key=idempotency_key,
        endpoint=f"POST /consignments-out/{out_id}/sale",
        payload=payload,
        operation=lambda conn: consignment.record_external_sale(conn, out_id, payload, user_id=ctx.user.id),
    )
