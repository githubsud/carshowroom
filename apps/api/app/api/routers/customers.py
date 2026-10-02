"""Customers (docs/API.md §3.5): phone-first records, balances, refunds of credit."""

from contextlib import AbstractContextManager
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query
from fastapi.responses import JSONResponse
from sqlalchemy import Connection

from app.api.deps import TenantContext, get_cipher, get_database, require, require_writable
from app.core.crypto import FieldCipher
from app.db.session import Database
from app.domain.finance import Page, PostingResult, Preview
from app.domain.permissions import Permission
from app.domain.vehicles import (
    CustomerDetail,
    CustomerIn,
    CustomerOut,
    CustomerRefundIn,
    CustomerRefundOut,
    CustomerUpdate,
    NationalIdOut,
)
from app.services import customers, idempotency

router = APIRouter(tags=["customers"])

IdempotencyKey = Annotated[str | None, Header(alias="Idempotency-Key")]


def _tx(db: Database, ctx: TenantContext) -> AbstractContextManager[Connection]:
    return db.transaction(user_id=ctx.user.id, tenant_id=ctx.tenant_id)


@router.get("/customers", response_model=Page[CustomerOut])
def list_customers(
    q: str | None = None,
    role: Literal["BUYER", "SELLER", "CONSIGNOR"] | None = None,
    include_archived: bool = False,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 25,
    ctx: TenantContext = Depends(require(Permission.CUSTOMER_VIEW)),
    db: Database = Depends(get_database),
) -> Page[CustomerOut]:
    with _tx(db, ctx) as conn:
        return customers.list_customers(
            conn, q=q, role=role, include_archived=include_archived, page=page, page_size=page_size
        )


@router.post("/customers", response_model=CustomerOut, status_code=201)
def create_customer(
    payload: CustomerIn,
    ctx: TenantContext = Depends(require(Permission.CUSTOMER_MANAGE)),
    db: Database = Depends(get_database),
    cipher: FieldCipher = Depends(get_cipher),
) -> CustomerOut:
    require_writable(ctx)
    with _tx(db, ctx) as conn:
        return customers.create_customer(conn, payload, cipher)


@router.get("/customers/{customer_id}", response_model=CustomerDetail)
def get_customer(
    customer_id: UUID,
    ctx: TenantContext = Depends(require(Permission.CUSTOMER_VIEW)),
    db: Database = Depends(get_database),
) -> JSONResponse:
    with _tx(db, ctx) as conn:
        detail = customers.detail(
            conn,
            customer_id,
            with_balances=ctx.can(Permission.CASH_VIEW),
            with_payables=ctx.can(Permission.VEHICLE_VIEW_COST),
        )
    # Keys a user may not see are left out entirely, not sent as null.
    hidden = {key for key in ("balances", "seller_payables") if getattr(detail, key) is None}
    return JSONResponse(detail.model_dump(mode="json", exclude=hidden))


@router.patch("/customers/{customer_id}", response_model=CustomerOut)
def update_customer(
    customer_id: UUID,
    payload: CustomerUpdate,
    ctx: TenantContext = Depends(require(Permission.CUSTOMER_MANAGE)),
    db: Database = Depends(get_database),
    cipher: FieldCipher = Depends(get_cipher),
) -> CustomerOut:
    require_writable(ctx)
    with _tx(db, ctx) as conn:
        return customers.update_customer(conn, customer_id, payload, cipher)


@router.get("/customers/{customer_id}/national-id", response_model=NationalIdOut)
def reveal_national_id(
    customer_id: UUID,
    ctx: TenantContext = Depends(require(Permission.CUSTOMER_VIEW_NATIONAL_ID)),
    db: Database = Depends(get_database),
    cipher: FieldCipher = Depends(get_cipher),
) -> NationalIdOut:
    with _tx(db, ctx) as conn:
        value = customers.reveal_national_id(conn, customer_id, cipher, actor=ctx.user.id, tenant_id=ctx.tenant_id)
    return NationalIdOut(national_id=value)


@router.post("/customers/{customer_id}/refunds/preview", response_model=Preview)
def preview_refund(
    customer_id: UUID,
    payload: CustomerRefundIn,
    ctx: TenantContext = Depends(require(Permission.CASH_TRANSACT)),
    db: Database = Depends(get_database),
) -> Preview:
    with _tx(db, ctx) as conn:
        return customers.preview_refund(conn, customer_id, payload, with_lines=ctx.can(Permission.JOURNAL_VIEW))


@router.post("/customers/{customer_id}/refunds", response_model=PostingResult[CustomerRefundOut], status_code=201)
def record_refund(
    customer_id: UUID,
    payload: CustomerRefundIn,
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
        endpoint=f"POST /customers/{customer_id}/refunds",
        payload=payload,
        operation=lambda conn: customers.record_refund(conn, customer_id, payload),
    )
