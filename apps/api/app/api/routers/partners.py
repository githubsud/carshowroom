"""Partners and capital (docs/API.md §3.3)."""

from contextlib import AbstractContextManager
from datetime import date
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header
from fastapi.responses import JSONResponse, Response
from sqlalchemy import Connection, text

from app.api.deps import TenantContext, get_cipher, get_database, require, require_any, require_writable
from app.core.crypto import FieldCipher
from app.core.errors import permission_denied
from app.db.session import Database
from app.domain.finance import PostingResult, Preview
from app.domain.partners import (
    NationalIdOut,
    PartnerIn,
    PartnerOut,
    PartnerStatementOut,
    PartnerSummaryOut,
    PartnerTransactionIn,
    PartnerTransactionOut,
    PartnerUpdate,
    ShareChangeIn,
    ShareOut,
)
from app.domain.permissions import Permission
from app.reports import partner_statement as statement_report
from app.services import finance, idempotency, partners

router = APIRouter(tags=["partners"])

IdempotencyKey = Annotated[str | None, Header(alias="Idempotency-Key")]
_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _tx(db: Database, ctx: TenantContext) -> AbstractContextManager[Connection]:
    return db.transaction(user_id=ctx.user.id, tenant_id=ctx.tenant_id)


def _can_see_partner(ctx: TenantContext, partner_id: UUID) -> bool:
    """partner.view_all sees everyone; a partner user sees only their own record."""
    return ctx.can(Permission.PARTNER_VIEW_ALL) or (
        ctx.can(Permission.PARTNER_VIEW_OWN) and ctx.partner_id == partner_id
    )


# --- Partners -------------------------------------------------------------------------------


@router.get("/partners", response_model=list[PartnerOut])
def list_partners(
    include_archived: bool = False,
    ctx: TenantContext = Depends(require(Permission.PARTNER_VIEW_ALL)),
    db: Database = Depends(get_database),
) -> list[PartnerOut]:
    with _tx(db, ctx) as conn:
        return partners.list_partners(conn, include_archived)


@router.post("/partners", response_model=PartnerOut, status_code=201)
def create_partner(
    payload: PartnerIn,
    ctx: TenantContext = Depends(require(Permission.PARTNER_EQUITY_CHANGE)),
    db: Database = Depends(get_database),
    cipher: FieldCipher = Depends(get_cipher),
) -> PartnerOut:
    require_writable(ctx)
    with _tx(db, ctx) as conn:
        return partners.create_partner(conn, payload, cipher)


@router.get("/partners/summary", response_model=PartnerSummaryOut)
def partners_summary(
    as_of: date | None = None,
    ctx: TenantContext = Depends(require_any(Permission.PARTNER_VIEW_ALL, Permission.PARTNER_VIEW_OWN)),
    db: Database = Depends(get_database),
) -> PartnerSummaryOut:
    with _tx(db, ctx) as conn:
        if not ctx.can(Permission.PARTNER_VIEW_ALL):
            # A partner sees the summary only if the showroom allows it (SPEC §1.2).
            allowed = conn.execute(text("select partner_sees_summary from public.tenant_settings")).scalar_one()
            if not allowed:
                raise permission_denied(str(Permission.PARTNER_VIEW_ALL))
        return partners.summary(conn, as_of)


@router.get("/partners/shares", response_model=list[ShareOut])
def current_shares(
    on_date: date | None = None,
    ctx: TenantContext = Depends(require(Permission.PARTNER_VIEW_ALL)),
    db: Database = Depends(get_database),
) -> list[ShareOut]:
    with _tx(db, ctx) as conn:
        return partners.shares_on(conn, on_date or finance.tenant_info(conn).today)


@router.get("/partners/shares/history", response_model=list[ShareOut])
def shares_history(
    ctx: TenantContext = Depends(require(Permission.PARTNER_VIEW_ALL)), db: Database = Depends(get_database)
) -> list[ShareOut]:
    with _tx(db, ctx) as conn:
        return partners.share_history(conn)


@router.post("/partners/shares", response_model=list[ShareOut], status_code=201)
def change_shares(
    payload: ShareChangeIn,
    ctx: TenantContext = Depends(require(Permission.PARTNER_EQUITY_CHANGE)),
    db: Database = Depends(get_database),
) -> list[ShareOut]:
    require_writable(ctx)
    with _tx(db, ctx) as conn:
        return partners.change_shares(conn, payload)


@router.get("/partners/{partner_id}", response_model=PartnerOut)
def get_partner(
    partner_id: UUID,
    ctx: TenantContext = Depends(require_any(Permission.PARTNER_VIEW_ALL, Permission.PARTNER_VIEW_OWN)),
    db: Database = Depends(get_database),
) -> PartnerOut:
    if not _can_see_partner(ctx, partner_id):
        raise permission_denied(str(Permission.PARTNER_VIEW_ALL))
    with _tx(db, ctx) as conn:
        return partners.get_partner(conn, partner_id)


@router.patch("/partners/{partner_id}", response_model=PartnerOut)
def update_partner(
    partner_id: UUID,
    payload: PartnerUpdate,
    ctx: TenantContext = Depends(require(Permission.PARTNER_EQUITY_CHANGE)),
    db: Database = Depends(get_database),
    cipher: FieldCipher = Depends(get_cipher),
) -> PartnerOut:
    require_writable(ctx)
    with _tx(db, ctx) as conn:
        return partners.update_partner(conn, partner_id, payload, cipher)


@router.get("/partners/{partner_id}/national-id", response_model=NationalIdOut)
def reveal_national_id(
    partner_id: UUID,
    ctx: TenantContext = Depends(require(Permission.PARTNER_EQUITY_CHANGE)),
    db: Database = Depends(get_database),
    cipher: FieldCipher = Depends(get_cipher),
) -> NationalIdOut:
    with _tx(db, ctx) as conn:
        value = partners.reveal_national_id(conn, partner_id, cipher, actor=ctx.user.id, tenant_id=ctx.tenant_id)
    return NationalIdOut(national_id=value)


# --- Partner money (rules 1-5, 28, 29) ----------------------------------------------------------


def _require_transaction_permissions(ctx: TenantContext, payload: PartnerTransactionIn) -> None:
    if not ctx.can(Permission.PARTNER_TRANSACT):
        raise permission_denied(str(Permission.PARTNER_TRANSACT))
    # Taking capital out changes the equity structure (docs/API.md §3.3).
    if payload.type == "CAPITAL_WITHDRAWAL" and not ctx.can(Permission.PARTNER_EQUITY_CHANGE):
        raise permission_denied(str(Permission.PARTNER_EQUITY_CHANGE))


@router.post("/partners/{partner_id}/transactions/preview", response_model=Preview)
def preview_transaction(
    partner_id: UUID,
    payload: PartnerTransactionIn,
    ctx: TenantContext = Depends(require()),
    db: Database = Depends(get_database),
) -> Preview:
    _require_transaction_permissions(ctx, payload)
    with _tx(db, ctx) as conn:
        return partners.preview_transaction(conn, partner_id, payload, with_lines=ctx.can(Permission.JOURNAL_VIEW))


@router.post(
    "/partners/{partner_id}/transactions", response_model=PostingResult[PartnerTransactionOut], status_code=201
)
def record_transaction(
    partner_id: UUID,
    payload: PartnerTransactionIn,
    idempotency_key: IdempotencyKey = None,
    ctx: TenantContext = Depends(require()),
    db: Database = Depends(get_database),
) -> JSONResponse:
    _require_transaction_permissions(ctx, payload)
    require_writable(ctx)
    return idempotency.run(
        db,
        user_id=ctx.user.id,
        tenant_id=ctx.tenant_id,
        key=idempotency_key,
        endpoint=f"POST /partners/{partner_id}/transactions",
        payload=payload,
        operation=lambda conn: partners.record_transaction(conn, partner_id, payload),
    )


@router.get("/partners/{partner_id}/transactions", response_model=list[PartnerTransactionOut])
def list_transactions(
    partner_id: UUID,
    ctx: TenantContext = Depends(require_any(Permission.PARTNER_VIEW_ALL, Permission.PARTNER_VIEW_OWN)),
    db: Database = Depends(get_database),
) -> list[PartnerTransactionOut]:
    if not _can_see_partner(ctx, partner_id):
        raise permission_denied(str(Permission.PARTNER_VIEW_ALL))
    with _tx(db, ctx) as conn:
        return partners.list_transactions(conn, partner_id)


# --- Statement ----------------------------------------------------------------------------------------


@router.get(
    "/partners/{partner_id}/statement",
    response_model=PartnerStatementOut,
    responses={200: {"content": {_XLSX: {}, "application/pdf": {}}}},
)
def partner_statement(
    partner_id: UUID,
    date_from: date,
    date_to: date,
    format: Literal["json", "xlsx", "pdf"] = "json",
    lang: Literal["ar", "en"] = "ar",
    ctx: TenantContext = Depends(require_any(Permission.PARTNER_VIEW_ALL, Permission.PARTNER_VIEW_OWN)),
    db: Database = Depends(get_database),
) -> PartnerStatementOut | Response:
    if not _can_see_partner(ctx, partner_id):
        raise permission_denied(str(Permission.PARTNER_VIEW_ALL))
    with _tx(db, ctx) as conn:
        statement = partners.statement(conn, partner_id, date_from, date_to)
        showroom = conn.execute(
            text("select name_ar, coalesce(name_en, name_ar) as name_en from public.tenants where id = :id"),
            {"id": ctx.tenant_id},
        ).one()
    if format == "json":
        return statement
    if format == "xlsx":
        content, media_type = statement_report.render_xlsx(statement, lang), _XLSX
    else:
        name = showroom.name_ar if lang == "ar" else showroom.name_en
        content, media_type = statement_report.render_pdf(statement, lang, name), "application/pdf"
    return Response(
        content,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{statement_report.filename(statement, format)}"'},
    )
