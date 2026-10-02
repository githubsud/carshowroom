"""Cash, bank, expenses, transfers, journal, periods and the cash book (docs/API.md §3.2)."""

from contextlib import AbstractContextManager
from datetime import date
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query
from fastapi.responses import JSONResponse, Response
from sqlalchemy import Connection, text

from app.api.deps import TenantContext, get_database, require, require_any, require_writable
from app.db.session import Database
from app.domain.finance import (
    CashAccountIn,
    CashAccountOut,
    CashAccountUpdate,
    CashBookOut,
    ExpenseCategoryIn,
    ExpenseCategoryOut,
    ExpenseCategoryUpdate,
    GeneralExpenseIn,
    GeneralExpenseOut,
    JournalEntryOut,
    LedgerAccountOut,
    Page,
    PaymentMethodOut,
    PeriodOut,
    PostingResult,
    Preview,
    ReverseIn,
    ReverseOut,
    TransferIn,
    TransferOut,
    UnlockIn,
)
from app.domain.permissions import Permission
from app.reports import cash_book as cash_book_report
from app.services import finance, idempotency, journal, periods

router = APIRouter()

IdempotencyKey = Annotated[str | None, Header(alias="Idempotency-Key")]
PageNo = Annotated[int, Query(ge=1)]
PageSize = Annotated[int, Query(ge=1, le=200)]


def _tx(db: Database, ctx: TenantContext) -> AbstractContextManager[Connection]:
    return db.transaction(user_id=ctx.user.id, tenant_id=ctx.tenant_id)


# --- Cash and bank accounts ------------------------------------------------------------------


@router.get("/cash-accounts", response_model=list[CashAccountOut], tags=["cash"])
def list_cash_accounts(
    include_archived: bool = False,
    ctx: TenantContext = Depends(require(Permission.CASH_VIEW)),
    db: Database = Depends(get_database),
) -> list[CashAccountOut]:
    with _tx(db, ctx) as conn:
        return finance.list_cash_accounts(conn, include_archived)


@router.post("/cash-accounts", response_model=CashAccountOut, status_code=201, tags=["cash"])
def create_cash_account(
    payload: CashAccountIn,
    ctx: TenantContext = Depends(require(Permission.TENANT_SETTINGS_MANAGE)),
    db: Database = Depends(get_database),
) -> CashAccountOut:
    require_writable(ctx)
    with _tx(db, ctx) as conn:
        return finance.create_cash_account(conn, payload)


@router.patch("/cash-accounts/{cash_account_id}", response_model=CashAccountOut, tags=["cash"])
def update_cash_account(
    cash_account_id: UUID,
    payload: CashAccountUpdate,
    ctx: TenantContext = Depends(require(Permission.TENANT_SETTINGS_MANAGE)),
    db: Database = Depends(get_database),
) -> CashAccountOut:
    require_writable(ctx)
    with _tx(db, ctx) as conn:
        return finance.update_cash_account(conn, cash_account_id, payload)


# --- Categories and payment methods ----------------------------------------------------------------


@router.get("/expense-categories", response_model=list[ExpenseCategoryOut], tags=["settings"])
def list_categories(
    kind: Literal["VEHICLE", "GENERAL"] | None = None,
    include_archived: bool = False,
    ctx: TenantContext = Depends(require()),
    db: Database = Depends(get_database),
) -> list[ExpenseCategoryOut]:
    with _tx(db, ctx) as conn:
        return finance.list_categories(conn, kind, include_archived)


@router.post("/expense-categories", response_model=ExpenseCategoryOut, status_code=201, tags=["settings"])
def create_category(
    payload: ExpenseCategoryIn,
    ctx: TenantContext = Depends(require(Permission.TENANT_SETTINGS_MANAGE)),
    db: Database = Depends(get_database),
) -> ExpenseCategoryOut:
    require_writable(ctx)
    with _tx(db, ctx) as conn:
        return finance.create_category(conn, payload)


@router.patch("/expense-categories/{category_id}", response_model=ExpenseCategoryOut, tags=["settings"])
def update_category(
    category_id: UUID,
    payload: ExpenseCategoryUpdate,
    ctx: TenantContext = Depends(require(Permission.TENANT_SETTINGS_MANAGE)),
    db: Database = Depends(get_database),
) -> ExpenseCategoryOut:
    require_writable(ctx)
    with _tx(db, ctx) as conn:
        return finance.update_category(conn, category_id, payload)


@router.get("/payment-methods", response_model=list[PaymentMethodOut], tags=["settings"])
def list_payment_methods(
    ctx: TenantContext = Depends(require()), db: Database = Depends(get_database)
) -> list[PaymentMethodOut]:
    with _tx(db, ctx) as conn:
        return finance.list_payment_methods(conn)


# --- General expenses (rule 20) -----------------------------------------------------------------------


@router.post("/general-expenses/preview", response_model=Preview, tags=["cash"])
def preview_expense(
    payload: GeneralExpenseIn,
    ctx: TenantContext = Depends(require(Permission.CASH_TRANSACT)),
    db: Database = Depends(get_database),
) -> Preview:
    with _tx(db, ctx) as conn:
        return finance.preview_expense(conn, payload, with_lines=ctx.can(Permission.JOURNAL_VIEW))


@router.post("/general-expenses", response_model=PostingResult[GeneralExpenseOut], status_code=201, tags=["cash"])
def record_expense(
    payload: GeneralExpenseIn,
    idempotency_key: IdempotencyKey = None,
    ctx: TenantContext = Depends(require(Permission.CASH_TRANSACT)),
    db: Database = Depends(get_database),
) -> JSONResponse:
    require_writable(ctx)
    return idempotency.run(
        db,
        user_id=ctx.user.id,
        tenant_id=ctx.tenant_id,
        key=idempotency_key,
        endpoint="POST /general-expenses",
        payload=payload,
        operation=lambda conn: finance.record_expense(conn, payload),
    )


@router.get("/general-expenses", response_model=Page[GeneralExpenseOut], tags=["cash"])
def list_expenses(
    date_from: date | None = None,
    date_to: date | None = None,
    category_id: UUID | None = None,
    page: PageNo = 1,
    page_size: PageSize = 25,
    ctx: TenantContext = Depends(require(Permission.CASH_VIEW)),
    db: Database = Depends(get_database),
) -> Page[GeneralExpenseOut]:
    with _tx(db, ctx) as conn:
        return finance.list_expenses(
            conn,
            date_from=date_from,
            date_to=date_to,
            category_id=category_id,
            page=page,
            page_size=page_size,
        )


# --- Transfers (rule 21) ---------------------------------------------------------------------------------


@router.post("/transfers/preview", response_model=Preview, tags=["cash"])
def preview_transfer(
    payload: TransferIn,
    ctx: TenantContext = Depends(require(Permission.CASH_TRANSACT)),
    db: Database = Depends(get_database),
) -> Preview:
    with _tx(db, ctx) as conn:
        return finance.preview_transfer(conn, payload, with_lines=ctx.can(Permission.JOURNAL_VIEW))


@router.post("/transfers", response_model=PostingResult[TransferOut], status_code=201, tags=["cash"])
def record_transfer(
    payload: TransferIn,
    idempotency_key: IdempotencyKey = None,
    ctx: TenantContext = Depends(require(Permission.CASH_TRANSACT)),
    db: Database = Depends(get_database),
) -> JSONResponse:
    require_writable(ctx)
    return idempotency.run(
        db,
        user_id=ctx.user.id,
        tenant_id=ctx.tenant_id,
        key=idempotency_key,
        endpoint="POST /transfers",
        payload=payload,
        operation=lambda conn: finance.record_transfer(conn, payload),
    )


@router.get("/transfers", response_model=Page[TransferOut], tags=["cash"])
def list_transfers(
    date_from: date | None = None,
    date_to: date | None = None,
    page: PageNo = 1,
    page_size: PageSize = 25,
    ctx: TenantContext = Depends(require(Permission.CASH_VIEW)),
    db: Database = Depends(get_database),
) -> Page[TransferOut]:
    with _tx(db, ctx) as conn:
        return finance.list_transfers(conn, date_from=date_from, date_to=date_to, page=page, page_size=page_size)


# --- Journal ----------------------------------------------------------------------------------------------


@router.get("/ledger-accounts", response_model=list[LedgerAccountOut], tags=["journal"])
def list_ledger_accounts(
    as_of: date | None = None,
    ctx: TenantContext = Depends(require(Permission.JOURNAL_VIEW)),
    db: Database = Depends(get_database),
) -> list[LedgerAccountOut]:
    with _tx(db, ctx) as conn:
        return journal.list_accounts(conn, as_of)


@router.get("/journal-entries", response_model=Page[JournalEntryOut], tags=["journal"])
def list_journal_entries(
    date_from: date | None = None,
    date_to: date | None = None,
    source_type: str | None = None,
    entry_no: int | None = None,
    page: PageNo = 1,
    page_size: PageSize = 25,
    ctx: TenantContext = Depends(require(Permission.JOURNAL_VIEW)),
    db: Database = Depends(get_database),
) -> Page[JournalEntryOut]:
    with _tx(db, ctx) as conn:
        return journal.list_entries(
            conn,
            date_from=date_from,
            date_to=date_to,
            source_type=source_type,
            entry_no=entry_no,
            page=page,
            page_size=page_size,
        )


@router.get("/journal-entries/{entry_id}", response_model=JournalEntryOut, tags=["journal"])
def get_journal_entry(
    entry_id: UUID,
    ctx: TenantContext = Depends(require(Permission.JOURNAL_VIEW)),
    db: Database = Depends(get_database),
) -> JournalEntryOut:
    with _tx(db, ctx) as conn:
        return journal.get_entry(conn, entry_id)


@router.post("/journal-entries/{entry_id}/reverse/preview", response_model=Preview, tags=["journal"])
def preview_reverse(
    entry_id: UUID,
    payload: ReverseIn,
    ctx: TenantContext = Depends(require(Permission.JOURNAL_REVERSE)),
    db: Database = Depends(get_database),
) -> Preview:
    with _tx(db, ctx) as conn:
        return journal.preview_reverse(conn, entry_id, payload)


@router.post("/journal-entries/{entry_id}/reverse", response_model=ReverseOut, status_code=201, tags=["journal"])
def reverse_journal_entry(
    entry_id: UUID,
    payload: ReverseIn,
    idempotency_key: IdempotencyKey = None,
    ctx: TenantContext = Depends(require(Permission.JOURNAL_REVERSE)),
    db: Database = Depends(get_database),
) -> JSONResponse:
    require_writable(ctx)
    return idempotency.run(
        db,
        user_id=ctx.user.id,
        tenant_id=ctx.tenant_id,
        key=idempotency_key,
        endpoint=f"POST /journal-entries/{entry_id}/reverse",
        payload=payload,
        operation=lambda conn: journal.reverse(conn, entry_id, payload),
    )


# --- Periods -------------------------------------------------------------------------------------------------


@router.get("/periods", response_model=list[PeriodOut], tags=["periods"])
def list_periods(
    ctx: TenantContext = Depends(require_any(Permission.CASH_VIEW, Permission.JOURNAL_VIEW)),
    db: Database = Depends(get_database),
) -> list[PeriodOut]:
    with _tx(db, ctx) as conn:
        return periods.list_periods(conn)


@router.post("/periods/{month}/lock", response_model=PeriodOut, tags=["periods"])
def lock_period(
    month: str,
    ctx: TenantContext = Depends(require(Permission.PERIOD_LOCK)),
    db: Database = Depends(get_database),
) -> PeriodOut:
    require_writable(ctx)
    first_day = periods.parse_month(month)
    with _tx(db, ctx) as conn:
        return periods.lock(conn, month=first_day, actor=ctx.user.id, tenant_id=ctx.tenant_id)


@router.post("/periods/{month}/unlock", response_model=PeriodOut, tags=["periods"])
def unlock_period(
    month: str,
    payload: UnlockIn,
    ctx: TenantContext = Depends(require(Permission.PERIOD_UNLOCK)),
    db: Database = Depends(get_database),
) -> PeriodOut:
    require_writable(ctx)
    first_day = periods.parse_month(month)
    with _tx(db, ctx) as conn:
        return periods.unlock(conn, month=first_day, reason=payload.reason, actor=ctx.user.id, tenant_id=ctx.tenant_id)


# --- Reports: cash book -----------------------------------------------------------------------------------------

_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@router.get(
    "/reports/cash-book",
    response_model=CashBookOut,
    tags=["reports"],
    responses={200: {"content": {_XLSX: {}, "application/pdf": {}}}},
)
def cash_book_report_endpoint(
    cash_account_id: UUID,
    date_from: date,
    date_to: date,
    format: Literal["json", "xlsx", "pdf"] = "json",
    lang: Literal["ar", "en"] = "ar",
    ctx: TenantContext = Depends(require(Permission.CASH_VIEW)),
    db: Database = Depends(get_database),
) -> CashBookOut | Response:
    with _tx(db, ctx) as conn:
        book = finance.cash_book(conn, cash_account_id, date_from, date_to)
        showroom = conn.execute(
            text("select name_ar, coalesce(name_en, name_ar) as name_en from public.tenants where id = :id"),
            {"id": ctx.tenant_id},
        ).one()
    if format == "json":
        return book
    if format == "xlsx":
        content, media_type = cash_book_report.render_xlsx(book, lang), _XLSX
    else:
        name = showroom.name_ar if lang == "ar" else showroom.name_en
        content, media_type = cash_book_report.render_pdf(book, lang, name), "application/pdf"
    return Response(
        content,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{cash_book_report.filename(book, format)}"'},
    )
