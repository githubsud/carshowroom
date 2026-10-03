"""Period close and profit distribution (docs/API.md §3.9)."""

from contextlib import AbstractContextManager
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header
from fastapi.responses import JSONResponse
from sqlalchemy import Connection

from app.api.deps import TenantContext, get_database, require, require_any, require_writable
from app.db.session import Database
from app.domain.distribution import DistributionIn, DistributionOut, DistributionPlanOut, DistributionReverseIn
from app.domain.finance import PostingResult
from app.domain.permissions import Permission
from app.services import distribution, idempotency

router = APIRouter(tags=["profit distribution"])

IdempotencyKey = Annotated[str | None, Header(alias="Idempotency-Key")]


def _tx(db: Database, ctx: TenantContext) -> AbstractContextManager[Connection]:
    return db.transaction(user_id=ctx.user.id, tenant_id=ctx.tenant_id)


@router.get("/distributions", response_model=list[DistributionOut])
def list_distributions(
    ctx: TenantContext = Depends(require_any(Permission.PROFIT_DISTRIBUTE, Permission.PARTNER_VIEW_ALL)),
    db: Database = Depends(get_database),
) -> list[DistributionOut]:
    with _tx(db, ctx) as conn:
        return distribution.list_distributions(conn)


@router.post("/distributions/preview", response_model=DistributionPlanOut)
def preview_distribution(
    payload: DistributionIn,
    ctx: TenantContext = Depends(require(Permission.PROFIT_DISTRIBUTE)),
    db: Database = Depends(get_database),
) -> DistributionPlanOut:
    with _tx(db, ctx) as conn:
        return distribution.preview(conn, payload)


@router.post("/distributions", response_model=PostingResult[DistributionOut], status_code=201)
def post_distribution(
    payload: DistributionIn,
    idempotency_key: IdempotencyKey = None,
    ctx: TenantContext = Depends(require(Permission.PROFIT_DISTRIBUTE)),
    db: Database = Depends(get_database),
) -> JSONResponse:
    require_writable(ctx)
    return idempotency.run(
        db,
        user_id=ctx.user.id,
        tenant_id=ctx.tenant_id,
        key=idempotency_key,
        endpoint="POST /distributions",
        payload=payload,
        operation=lambda conn: distribution.post(conn, payload, user_id=ctx.user.id),
    )


@router.get("/distributions/{distribution_id}", response_model=DistributionOut)
def get_distribution(
    distribution_id: UUID,
    ctx: TenantContext = Depends(require_any(Permission.PROFIT_DISTRIBUTE, Permission.PARTNER_VIEW_ALL)),
    db: Database = Depends(get_database),
) -> DistributionOut:
    with _tx(db, ctx) as conn:
        return distribution.get(conn, distribution_id)


@router.post("/distributions/{distribution_id}/reverse", response_model=DistributionOut)
def reverse_distribution(
    distribution_id: UUID,
    payload: DistributionReverseIn,
    ctx: TenantContext = Depends(require(Permission.PROFIT_DISTRIBUTE)),
    db: Database = Depends(get_database),
) -> DistributionOut:
    require_writable(ctx)
    with _tx(db, ctx) as conn:
        return distribution.reverse(conn, distribution_id, payload.reason, user_id=ctx.user.id)
