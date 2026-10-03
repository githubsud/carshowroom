"""Excel import, opening balances and the opening-equity clearing (docs/API.md §3.11)."""

from contextlib import AbstractContextManager
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header
from fastapi.responses import JSONResponse, Response
from sqlalchemy import Connection

from app.api.deps import TenantContext, get_cipher, get_database, require, require_writable
from app.core.crypto import FieldCipher
from app.db.session import Database
from app.domain.finance import PostingResult
from app.domain.imports import EquityClearingIn, ImportCreateIn, ImportJobOut, ImportMappingIn, OpeningEquityOut
from app.domain.permissions import Permission
from app.services import idempotency, imports

router = APIRouter(tags=["imports"])

IdempotencyKey = Annotated[str | None, Header(alias="Idempotency-Key")]
_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _tx(db: Database, ctx: TenantContext) -> AbstractContextManager[Connection]:
    return db.transaction(user_id=ctx.user.id, tenant_id=ctx.tenant_id)


def _xlsx(content: bytes, filename: str) -> Response:
    return Response(content, media_type=_XLSX, headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@router.get("/imports/template", response_class=Response, responses={200: {"content": {_XLSX: {}}}})
def template(
    lang: Literal["ar", "en"] = "ar", ctx: TenantContext = Depends(require(Permission.IMPORT_RUN))
) -> Response:
    return _xlsx(imports.template_xlsx(lang), "sayyara-import-template.xlsx")


@router.get("/imports", response_model=list[ImportJobOut])
def list_imports(
    ctx: TenantContext = Depends(require(Permission.IMPORT_RUN)), db: Database = Depends(get_database)
) -> list[ImportJobOut]:
    with _tx(db, ctx) as conn:
        return imports.list_jobs(conn)


@router.post("/imports", response_model=ImportJobOut, status_code=201)
def create_import(
    payload: ImportCreateIn,
    ctx: TenantContext = Depends(require(Permission.IMPORT_RUN)),
    db: Database = Depends(get_database),
) -> ImportJobOut:
    require_writable(ctx)
    with _tx(db, ctx) as conn:
        return imports.create(conn, payload)


@router.get("/imports/{job_id}", response_model=ImportJobOut)
def get_import(
    job_id: UUID, ctx: TenantContext = Depends(require(Permission.IMPORT_RUN)), db: Database = Depends(get_database)
) -> ImportJobOut:
    with _tx(db, ctx) as conn:
        return imports.get(conn, job_id)


@router.put("/imports/{job_id}/mapping", response_model=ImportJobOut)
def set_mapping(
    job_id: UUID,
    payload: ImportMappingIn,
    ctx: TenantContext = Depends(require(Permission.IMPORT_RUN)),
    db: Database = Depends(get_database),
) -> ImportJobOut:
    require_writable(ctx)
    with _tx(db, ctx) as conn:
        return imports.set_mapping(conn, job_id, payload)


@router.post("/imports/{job_id}/validate", response_model=ImportJobOut)
def validate_import(
    job_id: UUID, ctx: TenantContext = Depends(require(Permission.IMPORT_RUN)), db: Database = Depends(get_database)
) -> ImportJobOut:
    with _tx(db, ctx) as conn:
        return imports.validate(conn, job_id)


@router.get("/imports/{job_id}/errors", response_class=Response, responses={200: {"content": {_XLSX: {}}}})
def error_file(
    job_id: UUID,
    lang: Literal["ar", "en"] = "ar",
    ctx: TenantContext = Depends(require(Permission.IMPORT_RUN)),
    db: Database = Depends(get_database),
) -> Response:
    with _tx(db, ctx) as conn:
        content = imports.errors_xlsx(conn, job_id, lang)
    return _xlsx(content, "import-errors.xlsx")


@router.post("/imports/{job_id}/commit", response_model=PostingResult[ImportJobOut], status_code=201)
def commit_import(
    job_id: UUID,
    idempotency_key: IdempotencyKey = None,
    ctx: TenantContext = Depends(require(Permission.IMPORT_RUN)),
    db: Database = Depends(get_database),
    cipher: FieldCipher = Depends(get_cipher),
) -> JSONResponse:
    require_writable(ctx)
    return idempotency.run(
        db,
        user_id=ctx.user.id,
        tenant_id=ctx.tenant_id,
        key=idempotency_key,
        endpoint=f"POST /imports/{job_id}/commit",
        payload=None,
        operation=lambda conn: imports.commit(conn, job_id, cipher),
    )


@router.get("/opening-equity", response_model=OpeningEquityOut)
def opening_equity(
    ctx: TenantContext = Depends(require(Permission.PARTNER_EQUITY_CHANGE)), db: Database = Depends(get_database)
) -> OpeningEquityOut:
    with _tx(db, ctx) as conn:
        return imports.opening_equity(conn)


@router.post("/opening-equity/clear", response_model=PostingResult[OpeningEquityOut], status_code=201)
def clear_opening_equity(
    payload: EquityClearingIn,
    idempotency_key: IdempotencyKey = None,
    ctx: TenantContext = Depends(require(Permission.PARTNER_EQUITY_CHANGE)),
    db: Database = Depends(get_database),
) -> JSONResponse:
    require_writable(ctx)
    return idempotency.run(
        db,
        user_id=ctx.user.id,
        tenant_id=ctx.tenant_id,
        key=idempotency_key,
        endpoint="POST /opening-equity/clear",
        payload=payload,
        operation=lambda conn: imports.clear_opening_equity(conn, payload),
    )
