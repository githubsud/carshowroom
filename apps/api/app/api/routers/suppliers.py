"""Suppliers and workshops (D-23): records, statement, payments (rule 32)."""

from contextlib import AbstractContextManager
from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header
from fastapi.responses import JSONResponse
from sqlalchemy import Connection

from app.api.deps import TenantContext, get_database, require, require_writable
from app.db.session import Database
from app.domain.finance import PostingResult, Preview
from app.domain.permissions import Permission
from app.domain.vehicles import (
    SupplierIn,
    SupplierOut,
    SupplierPaymentIn,
    SupplierPaymentOut,
    SupplierStatementOut,
    SupplierUpdate,
)
from app.services import idempotency, suppliers

router = APIRouter(tags=["suppliers"])

IdempotencyKey = Annotated[str | None, Header(alias="Idempotency-Key")]


def _tx(db: Database, ctx: TenantContext) -> AbstractContextManager[Connection]:
    return db.transaction(user_id=ctx.user.id, tenant_id=ctx.tenant_id)


@router.get("/suppliers", response_model=list[SupplierOut])
def list_suppliers(
    include_archived: bool = False,
    ctx: TenantContext = Depends(require(Permission.SUPPLIER_MANAGE)),
    db: Database = Depends(get_database),
) -> list[SupplierOut]:
    with _tx(db, ctx) as conn:
        return suppliers.list_suppliers(conn, include_archived)


@router.post("/suppliers", response_model=SupplierOut, status_code=201)
def create_supplier(
    payload: SupplierIn,
    ctx: TenantContext = Depends(require(Permission.SUPPLIER_MANAGE)),
    db: Database = Depends(get_database),
) -> SupplierOut:
    require_writable(ctx)
    with _tx(db, ctx) as conn:
        return suppliers.create_supplier(conn, payload)


@router.patch("/suppliers/{supplier_id}", response_model=SupplierOut)
def update_supplier(
    supplier_id: UUID,
    payload: SupplierUpdate,
    ctx: TenantContext = Depends(require(Permission.SUPPLIER_MANAGE)),
    db: Database = Depends(get_database),
) -> SupplierOut:
    require_writable(ctx)
    with _tx(db, ctx) as conn:
        return suppliers.update_supplier(conn, supplier_id, payload)


@router.get("/suppliers/{supplier_id}/statement", response_model=SupplierStatementOut)
def supplier_statement(
    supplier_id: UUID,
    date_from: date,
    date_to: date,
    ctx: TenantContext = Depends(require(Permission.SUPPLIER_MANAGE)),
    db: Database = Depends(get_database),
) -> SupplierStatementOut:
    with _tx(db, ctx) as conn:
        return suppliers.statement(conn, supplier_id, date_from, date_to)


@router.post("/suppliers/{supplier_id}/payments/preview", response_model=Preview)
def preview_payment(
    supplier_id: UUID,
    payload: SupplierPaymentIn,
    ctx: TenantContext = Depends(require(Permission.SUPPLIER_PAY)),
    db: Database = Depends(get_database),
) -> Preview:
    with _tx(db, ctx) as conn:
        return suppliers.preview_payment(conn, supplier_id, payload, with_lines=ctx.can(Permission.JOURNAL_VIEW))


@router.post("/suppliers/{supplier_id}/payments", response_model=PostingResult[SupplierPaymentOut], status_code=201)
def record_payment(
    supplier_id: UUID,
    payload: SupplierPaymentIn,
    idempotency_key: IdempotencyKey = None,
    ctx: TenantContext = Depends(require(Permission.SUPPLIER_PAY)),
    db: Database = Depends(get_database),
) -> JSONResponse:
    require_writable(ctx)
    return idempotency.run(
        db,
        user_id=ctx.user.id,
        tenant_id=ctx.tenant_id,
        key=idempotency_key,
        endpoint=f"POST /suppliers/{supplier_id}/payments",
        payload=payload,
        operation=lambda conn: suppliers.record_payment(conn, supplier_id, payload),
    )
