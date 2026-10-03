"""Vehicles (docs/API.md §3.4): records and lifecycle, locations, inventory, the
vehicle file, purchase, vehicle expenses, photos, documents and quick search.

Every vehicle response passes through app.api.masking, so users without
vehicle.view_cost / vehicle.view_min_price never receive those keys (SPEC §10).
"""

from contextlib import AbstractContextManager
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query
from fastapi.responses import JSONResponse, Response
from sqlalchemy import Connection

from app.api.deps import TenantContext, get_database, get_storage, require, require_any, require_writable
from app.api.masking import masked
from app.core.errors import AppError, permission_denied
from app.db.session import Database
from app.domain.finance import PostingResult, Preview
from app.domain.permissions import Permission
from app.domain.vehicles import (
    DocumentEntity,
    DocumentOut,
    DocumentRegisterIn,
    DocumentUploadIn,
    LocationIn,
    LocationOut,
    LocationUpdate,
    MediaOut,
    MediaRegisterIn,
    MediaUploadIn,
    PurchaseIn,
    PurchaseOut,
    SearchOut,
    SellerPaymentIn,
    SellerPaymentOut,
    SignedUrlOut,
    SplitVehicleExpenseIn,
    SplitVehicleExpenseOut,
    UploadTicket,
    VehicleDetail,
    VehicleExpenseIn,
    VehicleExpenseOut,
    VehicleIn,
    VehicleMoveIn,
    VehiclePage,
    VehicleStatus,
    VehicleStatusIn,
    VehicleUpdate,
)
from app.integrations.storage import Storage
from app.services import customers, idempotency, vehicles

router = APIRouter(tags=["vehicles"])

IdempotencyKey = Annotated[str | None, Header(alias="Idempotency-Key")]


def _tx(db: Database, ctx: TenantContext) -> AbstractContextManager[Connection]:
    return db.transaction(user_id=ctx.user.id, tenant_id=ctx.tenant_id)


def _detail(conn: Connection, ctx: TenantContext, storage: Storage, vehicle_id: UUID) -> VehicleDetail:
    return vehicles.get_detail(conn, vehicle_id, storage, can_view_cost=ctx.can(Permission.VEHICLE_VIEW_COST))


def _check_min_price(ctx: TenantContext, payload: VehicleIn | VehicleUpdate) -> None:
    if "min_price" in payload.model_fields_set and not ctx.can(Permission.VEHICLE_VIEW_MIN_PRICE):
        raise permission_denied(str(Permission.VEHICLE_VIEW_MIN_PRICE))


# --- Locations --------------------------------------------------------------------------------


@router.get("/locations", response_model=list[LocationOut], tags=["settings"])
def list_locations(
    include_archived: bool = False,
    ctx: TenantContext = Depends(require(Permission.VEHICLE_VIEW)),
    db: Database = Depends(get_database),
) -> list[LocationOut]:
    with _tx(db, ctx) as conn:
        return vehicles.list_locations(conn, include_archived)


@router.post("/locations", response_model=LocationOut, status_code=201, tags=["settings"])
def create_location(
    payload: LocationIn,
    ctx: TenantContext = Depends(require(Permission.TENANT_SETTINGS_MANAGE)),
    db: Database = Depends(get_database),
) -> LocationOut:
    require_writable(ctx)
    with _tx(db, ctx) as conn:
        return vehicles.create_location(conn, payload)


@router.patch("/locations/{location_id}", response_model=LocationOut, tags=["settings"])
def update_location(
    location_id: UUID,
    payload: LocationUpdate,
    ctx: TenantContext = Depends(require(Permission.TENANT_SETTINGS_MANAGE)),
    db: Database = Depends(get_database),
) -> LocationOut:
    require_writable(ctx)
    with _tx(db, ctx) as conn:
        return vehicles.update_location(conn, location_id, payload)


# --- Search -----------------------------------------------------------------------------------------


@router.get("/search", response_model=SearchOut, tags=["search"])
def quick_search(
    q: Annotated[str, Query(min_length=2, max_length=60)],
    ctx: TenantContext = Depends(require_any(Permission.VEHICLE_VIEW, Permission.CUSTOMER_VIEW)),
    db: Database = Depends(get_database),
) -> SearchOut:
    with _tx(db, ctx) as conn:
        return SearchOut(
            vehicles=vehicles.search(conn, q) if ctx.can(Permission.VEHICLE_VIEW) else [],
            customers=customers.search(conn, q) if ctx.can(Permission.CUSTOMER_VIEW) else [],
        )


# --- Vehicles ----------------------------------------------------------------------------------------


@router.get("/vehicles", response_model=VehiclePage)
def list_vehicles(
    status: Annotated[list[VehicleStatus] | None, Query()] = None,
    make: str | None = None,
    year: int | None = None,
    location_id: UUID | None = None,
    ownership_type: Literal["OWNED", "CONSIGNED_IN"] | None = None,
    aging: Literal["FRESH", "AGING", "OLD", "STALE"] | None = None,
    q: str | None = None,
    sort: Literal["stock_date", "-stock_date", "price", "-price", "make", "-created"] = "-created",
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 25,
    ctx: TenantContext = Depends(require(Permission.VEHICLE_VIEW)),
    db: Database = Depends(get_database),
    storage: Storage = Depends(get_storage),
) -> JSONResponse:
    with _tx(db, ctx) as conn:
        result = vehicles.list_vehicles(
            conn,
            storage,
            statuses=list(status) if status else None,
            make=make,
            year=year,
            location_id=location_id,
            ownership_type=ownership_type,
            q=q,
            aging=aging,
            sort=sort,
            page=page,
            page_size=page_size,
        )
    return masked(result, ctx)


@router.post("/vehicles", response_model=VehicleDetail, status_code=201)
def create_vehicle(
    payload: VehicleIn,
    ctx: TenantContext = Depends(require(Permission.VEHICLE_MANAGE)),
    db: Database = Depends(get_database),
    storage: Storage = Depends(get_storage),
) -> JSONResponse:
    require_writable(ctx)
    _check_min_price(ctx, payload)
    with _tx(db, ctx) as conn:
        vehicle_id = vehicles.create_vehicle(conn, payload)
        detail = _detail(conn, ctx, storage, vehicle_id)
    return masked(detail, ctx, status_code=201)


@router.get("/vehicles/{vehicle_id}", response_model=VehicleDetail)
def get_vehicle(
    vehicle_id: UUID,
    ctx: TenantContext = Depends(require(Permission.VEHICLE_VIEW)),
    db: Database = Depends(get_database),
    storage: Storage = Depends(get_storage),
) -> JSONResponse:
    with _tx(db, ctx) as conn:
        detail = _detail(conn, ctx, storage, vehicle_id)
    return masked(detail, ctx)


@router.patch("/vehicles/{vehicle_id}", response_model=VehicleDetail)
def update_vehicle(
    vehicle_id: UUID,
    payload: VehicleUpdate,
    ctx: TenantContext = Depends(require(Permission.VEHICLE_MANAGE)),
    db: Database = Depends(get_database),
    storage: Storage = Depends(get_storage),
) -> JSONResponse:
    require_writable(ctx)
    _check_min_price(ctx, payload)
    with _tx(db, ctx) as conn:
        vehicles.update_vehicle(conn, vehicle_id, payload)
        detail = _detail(conn, ctx, storage, vehicle_id)
    return masked(detail, ctx)


@router.post("/vehicles/{vehicle_id}/status", response_model=VehicleDetail)
def change_status(
    vehicle_id: UUID,
    payload: VehicleStatusIn,
    ctx: TenantContext = Depends(require(Permission.VEHICLE_MANAGE)),
    db: Database = Depends(get_database),
    storage: Storage = Depends(get_storage),
) -> JSONResponse:
    require_writable(ctx)
    with _tx(db, ctx) as conn:
        vehicles.change_status(conn, vehicle_id, payload.status, payload.reason)
        detail = _detail(conn, ctx, storage, vehicle_id)
    return masked(detail, ctx)


@router.post("/vehicles/{vehicle_id}/move", response_model=VehicleDetail)
def move_vehicle(
    vehicle_id: UUID,
    payload: VehicleMoveIn,
    ctx: TenantContext = Depends(require(Permission.VEHICLE_MANAGE)),
    db: Database = Depends(get_database),
    storage: Storage = Depends(get_storage),
) -> JSONResponse:
    require_writable(ctx)
    with _tx(db, ctx) as conn:
        vehicles.move(conn, vehicle_id, payload.location_id, payload.reason)
        detail = _detail(conn, ctx, storage, vehicle_id)
    return masked(detail, ctx)


# --- Purchase (rules 6, 7) and seller payments (rule 8) --------------------------------------------------


@router.post("/vehicles/{vehicle_id}/purchase/preview", response_model=Preview)
def preview_purchase(
    vehicle_id: UUID,
    payload: PurchaseIn,
    ctx: TenantContext = Depends(require(Permission.VEHICLE_PURCHASE)),
    db: Database = Depends(get_database),
) -> Preview:
    with _tx(db, ctx) as conn:
        return vehicles.preview_purchase(conn, vehicle_id, payload, with_lines=ctx.can(Permission.JOURNAL_VIEW))


@router.post("/vehicles/{vehicle_id}/purchase", response_model=PostingResult[PurchaseOut], status_code=201)
def record_purchase(
    vehicle_id: UUID,
    payload: PurchaseIn,
    idempotency_key: IdempotencyKey = None,
    ctx: TenantContext = Depends(require(Permission.VEHICLE_PURCHASE)),
    db: Database = Depends(get_database),
) -> JSONResponse:
    require_writable(ctx)
    return idempotency.run(
        db,
        user_id=ctx.user.id,
        tenant_id=ctx.tenant_id,
        key=idempotency_key,
        endpoint=f"POST /vehicles/{vehicle_id}/purchase",
        payload=payload,
        operation=lambda conn: vehicles.record_purchase(conn, vehicle_id, payload),
    )


@router.post("/vehicles/{vehicle_id}/seller-payments/preview", response_model=Preview)
def preview_seller_payment(
    vehicle_id: UUID,
    payload: SellerPaymentIn,
    ctx: TenantContext = Depends(require(Permission.VEHICLE_PURCHASE, Permission.CASH_TRANSACT)),
    db: Database = Depends(get_database),
) -> Preview:
    with _tx(db, ctx) as conn:
        return vehicles.preview_seller_payment(conn, vehicle_id, payload, with_lines=ctx.can(Permission.JOURNAL_VIEW))


@router.post("/vehicles/{vehicle_id}/seller-payments", response_model=PostingResult[SellerPaymentOut], status_code=201)
def record_seller_payment(
    vehicle_id: UUID,
    payload: SellerPaymentIn,
    idempotency_key: IdempotencyKey = None,
    ctx: TenantContext = Depends(require(Permission.VEHICLE_PURCHASE, Permission.CASH_TRANSACT)),
    db: Database = Depends(get_database),
) -> JSONResponse:
    require_writable(ctx)
    return idempotency.run(
        db,
        user_id=ctx.user.id,
        tenant_id=ctx.tenant_id,
        key=idempotency_key,
        endpoint=f"POST /vehicles/{vehicle_id}/seller-payments",
        payload=payload,
        operation=lambda conn: vehicles.record_seller_payment(conn, vehicle_id, payload),
    )


# --- Vehicle expenses (rules 9, 30, 31; P-04) --------------------------------------------------------------


@router.get("/vehicles/{vehicle_id}/expenses", response_model=list[VehicleExpenseOut])
def list_expenses(
    vehicle_id: UUID,
    ctx: TenantContext = Depends(require(Permission.VEHICLE_VIEW_COST)),
    db: Database = Depends(get_database),
) -> list[VehicleExpenseOut]:
    with _tx(db, ctx) as conn:
        return vehicles.list_expenses(conn, vehicle_id)


@router.post("/vehicles/{vehicle_id}/expenses/preview", response_model=Preview)
def preview_expense(
    vehicle_id: UUID,
    payload: VehicleExpenseIn,
    ctx: TenantContext = Depends(require(Permission.VEHICLE_EXPENSE_RECORD)),
    db: Database = Depends(get_database),
) -> Preview:
    with _tx(db, ctx) as conn:
        return vehicles.preview_expense(conn, vehicle_id, payload, with_lines=ctx.can(Permission.JOURNAL_VIEW))


@router.post("/vehicles/{vehicle_id}/expenses", response_model=PostingResult[VehicleExpenseOut], status_code=201)
def record_expense(
    vehicle_id: UUID,
    payload: VehicleExpenseIn,
    idempotency_key: IdempotencyKey = None,
    ctx: TenantContext = Depends(require(Permission.VEHICLE_EXPENSE_RECORD)),
    db: Database = Depends(get_database),
) -> JSONResponse:
    require_writable(ctx)
    return idempotency.run(
        db,
        user_id=ctx.user.id,
        tenant_id=ctx.tenant_id,
        key=idempotency_key,
        endpoint=f"POST /vehicles/{vehicle_id}/expenses",
        payload=payload,
        operation=lambda conn: vehicles.record_expense(conn, vehicle_id, payload),
    )


@router.post("/vehicle-expenses/split/preview", response_model=Preview)
def preview_split_expense(
    payload: SplitVehicleExpenseIn,
    ctx: TenantContext = Depends(require(Permission.VEHICLE_EXPENSE_RECORD)),
    db: Database = Depends(get_database),
) -> Preview:
    with _tx(db, ctx) as conn:
        return vehicles.preview_split_expense(conn, payload, with_lines=ctx.can(Permission.JOURNAL_VIEW))


@router.post("/vehicle-expenses/split", response_model=PostingResult[SplitVehicleExpenseOut], status_code=201)
def record_split_expense(
    payload: SplitVehicleExpenseIn,
    idempotency_key: IdempotencyKey = None,
    ctx: TenantContext = Depends(require(Permission.VEHICLE_EXPENSE_RECORD)),
    db: Database = Depends(get_database),
) -> JSONResponse:
    """One direct expense shared by several cars (pilot review, D-71)."""
    require_writable(ctx)
    return idempotency.run(
        db,
        user_id=ctx.user.id,
        tenant_id=ctx.tenant_id,
        key=idempotency_key,
        endpoint="POST /vehicle-expenses/split",
        payload=payload,
        operation=lambda conn: vehicles.record_split_expense(conn, payload),
    )


# --- Photos -------------------------------------------------------------------------------------------------


@router.post("/vehicles/{vehicle_id}/media/upload-url", response_model=UploadTicket)
def media_upload_url(
    vehicle_id: UUID,
    payload: MediaUploadIn,
    ctx: TenantContext = Depends(require(Permission.VEHICLE_MANAGE)),
    db: Database = Depends(get_database),
    storage: Storage = Depends(get_storage),
) -> UploadTicket:
    require_writable(ctx)
    with _tx(db, ctx) as conn:
        return vehicles.media_ticket(conn, storage, vehicle_id, payload)


@router.post("/vehicles/{vehicle_id}/media", response_model=MediaOut, status_code=201)
def register_media(
    vehicle_id: UUID,
    payload: MediaRegisterIn,
    ctx: TenantContext = Depends(require(Permission.VEHICLE_MANAGE)),
    db: Database = Depends(get_database),
    storage: Storage = Depends(get_storage),
) -> MediaOut:
    require_writable(ctx)
    with _tx(db, ctx) as conn:
        return vehicles.register_media(conn, storage, vehicle_id, payload)


@router.delete("/vehicles/{vehicle_id}/media/{media_id}", status_code=204)
def remove_media(
    vehicle_id: UUID,
    media_id: UUID,
    ctx: TenantContext = Depends(require(Permission.VEHICLE_MANAGE)),
    db: Database = Depends(get_database),
) -> Response:
    require_writable(ctx)
    with _tx(db, ctx) as conn:
        vehicles.archive_media(conn, vehicle_id, media_id)
    return Response(status_code=204)


# --- Documents ------------------------------------------------------------------------------------------------

_VIEW = {
    "VEHICLE": Permission.VEHICLE_VIEW,
    "CUSTOMER": Permission.CUSTOMER_VIEW,
    "SALE": Permission.SALE_VIEW,
    "SUPPLIER": Permission.SUPPLIER_MANAGE,
}
_MANAGE = {
    "VEHICLE": Permission.VEHICLE_MANAGE,
    "CUSTOMER": Permission.CUSTOMER_MANAGE,
    "SALE": Permission.SALE_DRAFT,
    "SUPPLIER": Permission.SUPPLIER_MANAGE,
}


def _require_document(ctx: TenantContext, entity_type: str, doc_type: str | None, *, manage: bool) -> None:
    permission = (_MANAGE if manage else _VIEW)[entity_type]
    if not ctx.can(permission):
        raise permission_denied(str(permission))
    # Purchase contracts and seller receipts show what the car cost (G-09).
    if (
        doc_type is not None
        and vehicles.document_sensitivity(doc_type) == "COST"
        and not ctx.can(Permission.VEHICLE_VIEW_COST)
    ):
        raise permission_denied(str(Permission.VEHICLE_VIEW_COST))


@router.post("/documents/upload-url", response_model=UploadTicket, tags=["documents"])
def document_upload_url(
    payload: DocumentUploadIn,
    ctx: TenantContext = Depends(require()),
    db: Database = Depends(get_database),
    storage: Storage = Depends(get_storage),
) -> UploadTicket:
    require_writable(ctx)
    _require_document(ctx, payload.entity_type, payload.doc_type, manage=True)
    with _tx(db, ctx) as conn:
        return vehicles.document_ticket(conn, storage, payload)


@router.post("/documents", response_model=DocumentOut, status_code=201, tags=["documents"])
def register_document(
    payload: DocumentRegisterIn,
    ctx: TenantContext = Depends(require()),
    db: Database = Depends(get_database),
    storage: Storage = Depends(get_storage),
) -> DocumentOut:
    require_writable(ctx)
    _require_document(ctx, payload.entity_type, payload.doc_type, manage=True)
    with _tx(db, ctx) as conn:
        return vehicles.register_document(conn, storage, payload)


@router.get("/documents", response_model=list[DocumentOut], tags=["documents"])
def list_documents(
    entity_type: DocumentEntity,
    entity_id: UUID,
    ctx: TenantContext = Depends(require()),
    db: Database = Depends(get_database),
) -> list[DocumentOut]:
    _require_document(ctx, entity_type, None, manage=False)
    with _tx(db, ctx) as conn:
        return vehicles.list_documents(
            conn, entity_type, entity_id, can_view_cost=ctx.can(Permission.VEHICLE_VIEW_COST)
        )


def _document_access(conn: Connection, ctx: TenantContext, document_id: UUID, *, manage: bool) -> None:
    row = vehicles.document_record(conn, document_id)
    try:
        _require_document(ctx, row.entity_type, row.doc_type, manage=manage)
    except AppError as exc:
        # A hidden document is reported as missing, not as forbidden.
        raise AppError("NOT_FOUND", "document not found", status_code=404) from exc


@router.get("/documents/{document_id}/url", response_model=SignedUrlOut, tags=["documents"])
def document_url(
    document_id: UUID,
    ctx: TenantContext = Depends(require()),
    db: Database = Depends(get_database),
    storage: Storage = Depends(get_storage),
) -> SignedUrlOut:
    with _tx(db, ctx) as conn:
        _document_access(conn, ctx, document_id, manage=False)
        return SignedUrlOut(url=vehicles.document_url(conn, storage, document_id))


@router.delete("/documents/{document_id}", status_code=204, tags=["documents"])
def remove_document(
    document_id: UUID,
    ctx: TenantContext = Depends(require()),
    db: Database = Depends(get_database),
) -> Response:
    require_writable(ctx)
    with _tx(db, ctx) as conn:
        _document_access(conn, ctx, document_id, manage=True)
        vehicles.archive_document(conn, document_id)
    return Response(status_code=204)
