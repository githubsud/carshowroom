"""Customer requests, matches and follow-ups (docs/API.md §3.9)."""

from contextlib import AbstractContextManager
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import Connection

from app.api.deps import TenantContext, get_database, require, require_writable
from app.db.session import Database
from app.domain.consignment import (
    CustomerRequestIn,
    CustomerRequestOut,
    CustomerRequestUpdate,
    FollowUpDue,
    FollowUpIn,
    FollowUpOut,
    RequestMatch,
    RequestStatus,
)
from app.domain.permissions import Permission
from app.services import crm

router = APIRouter(tags=["customer requests"])


class ContactedIn(BaseModel):
    contacted: bool = True


def _tx(db: Database, ctx: TenantContext) -> AbstractContextManager[Connection]:
    return db.transaction(user_id=ctx.user.id, tenant_id=ctx.tenant_id)


@router.get("/customer-requests", response_model=list[CustomerRequestOut])
def list_requests(
    status: RequestStatus | None = None,
    customer_id: UUID | None = None,
    open_only: bool = True,
    q: str | None = None,
    ctx: TenantContext = Depends(require(Permission.CUSTOMER_VIEW)),
    db: Database = Depends(get_database),
) -> list[CustomerRequestOut]:
    with _tx(db, ctx) as conn:
        return crm.list_requests(conn, status=status, customer_id=customer_id, open_only=open_only, q=q)


@router.post("/customer-requests", response_model=CustomerRequestOut, status_code=201)
def create_request(
    payload: CustomerRequestIn,
    ctx: TenantContext = Depends(require(Permission.REQUEST_MANAGE)),
    db: Database = Depends(get_database),
) -> CustomerRequestOut:
    require_writable(ctx)
    with _tx(db, ctx) as conn:
        return crm.create_request(conn, payload)


@router.get("/customer-requests/{request_id}", response_model=CustomerRequestOut)
def get_request(
    request_id: UUID,
    ctx: TenantContext = Depends(require(Permission.CUSTOMER_VIEW)),
    db: Database = Depends(get_database),
) -> CustomerRequestOut:
    with _tx(db, ctx) as conn:
        return crm.get_request(conn, request_id)


@router.patch("/customer-requests/{request_id}", response_model=CustomerRequestOut)
def update_request(
    request_id: UUID,
    changes: CustomerRequestUpdate,
    ctx: TenantContext = Depends(require(Permission.REQUEST_MANAGE)),
    db: Database = Depends(get_database),
) -> CustomerRequestOut:
    require_writable(ctx)
    with _tx(db, ctx) as conn:
        return crm.update_request(conn, request_id, changes)


@router.get("/vehicles/{vehicle_id}/request-matches", response_model=list[RequestMatch], tags=["vehicles"])
def vehicle_matches(
    vehicle_id: UUID,
    ctx: TenantContext = Depends(require(Permission.CUSTOMER_VIEW)),
    db: Database = Depends(get_database),
) -> list[RequestMatch]:
    with _tx(db, ctx) as conn:
        return crm.vehicle_matches(conn, vehicle_id)


@router.put("/request-matches/{match_id}/contacted", response_model=RequestMatch)
def set_contacted(
    match_id: UUID,
    payload: ContactedIn,
    ctx: TenantContext = Depends(require(Permission.REQUEST_MANAGE)),
    db: Database = Depends(get_database),
) -> RequestMatch:
    require_writable(ctx)
    with _tx(db, ctx) as conn:
        return crm.set_contacted(conn, match_id, contacted=payload.contacted, user_id=ctx.user.id)


@router.get("/follow-ups", response_model=list[FollowUpOut], tags=["follow-ups"])
def list_follow_ups(
    customer_id: UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    ctx: TenantContext = Depends(require(Permission.CUSTOMER_VIEW)),
    db: Database = Depends(get_database),
) -> list[FollowUpOut]:
    with _tx(db, ctx) as conn:
        return crm.list_follow_ups(conn, customer_id=customer_id, limit=limit)


@router.get("/follow-ups/due", response_model=list[FollowUpDue], tags=["follow-ups"])
def due_follow_ups(
    mine: bool = False,
    ctx: TenantContext = Depends(require(Permission.CUSTOMER_VIEW)),
    db: Database = Depends(get_database),
) -> list[FollowUpDue]:
    with _tx(db, ctx) as conn:
        return crm.due_follow_ups(conn, assigned_to=ctx.user.id if mine else None)


@router.post("/follow-ups", response_model=FollowUpOut, status_code=201, tags=["follow-ups"])
def log_follow_up(
    payload: FollowUpIn,
    ctx: TenantContext = Depends(require(Permission.FOLLOWUP_MANAGE)),
    db: Database = Depends(get_database),
) -> FollowUpOut:
    require_writable(ctx)
    with _tx(db, ctx) as conn:
        return crm.log_follow_up(conn, payload, user_id=ctx.user.id)
