"""Vehicles (SPEC §4.3): master data, the status lifecycle, locations, the
inventory list, the vehicle file (cost and profit), purchase (rules 6-8),
vehicle expenses (rules 9, 30, 31, P-04), photos and documents.

Cost is never stored: a car's cost is its balance on vehicle inventory (1300)
plus anything charged to cost of sales (5000) for it, and its profit is
vehicle sales (4100) minus cost of sales for it (D-26, D-34). Responses carry
cost fields that the routers strip for users without vehicle.view_cost.
"""

import contextlib
from collections.abc import Generator
from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Connection, text
from sqlalchemy.exc import DBAPIError, IntegrityError

from app.core.errors import AppError, not_found
from app.domain.finance import EntryRef, PostingResult, Preview, PreviewEffect
from app.domain.ledger import ZERO, EntryDraft
from app.domain.money import format_money, ltr, quantize
from app.domain.vehicles import (
    ActiveReservation,
    Aging,
    CostLine,
    DocumentOut,
    DocumentRegisterIn,
    DocumentUploadIn,
    LocationChange,
    LocationIn,
    LocationOut,
    LocationUpdate,
    MediaOut,
    MediaRegisterIn,
    MediaUploadIn,
    PriceChange,
    PurchaseIn,
    PurchaseOut,
    PurchaseSummary,
    SellerPaymentIn,
    SellerPaymentOut,
    StatusChange,
    UploadTicket,
    VehicleCost,
    VehicleDetail,
    VehicleExpenseIn,
    VehicleExpenseOut,
    VehicleHit,
    VehicleIn,
    VehiclePage,
    VehicleProfit,
    VehicleRow,
    VehicleSaleInfo,
    VehicleStatus,
    VehicleUpdate,
)
from app.integrations.storage import Storage
from app.services import customers, finance, suppliers
from app.services.posting import engine, rules

MEDIA_BUCKET = "vehicle-media"
DOCUMENT_BUCKET = "documents"
IN_STOCK: tuple[VehicleStatus, ...] = ("IN_PREPARATION", "AVAILABLE", "RESERVED", "AT_OTHER_SHOWROOM")
# Transitions a user may make directly; the others happen through a purchase,
# reservation, sale, cancellation or (Phase 6) consignment flow.
MANUAL_TRANSITIONS = {
    ("DRAFT", "IN_PREPARATION"),
    ("IN_PREPARATION", "AVAILABLE"),
    ("SOLD", "DELIVERED"),
    ("DRAFT", "ARCHIVED"),
    ("IN_PREPARATION", "ARCHIVED"),
    ("AVAILABLE", "ARCHIVED"),
}
_EXTENSIONS = {"image/webp": "webp", "image/jpeg": "jpg", "image/png": "png", "application/pdf": "pdf"}
_COST_DOCUMENTS = {"PURCHASE_CONTRACT", "SELLER_RECEIPT"}


def vehicle_label(make: str, model: str, year: int | None) -> str:
    return " ".join(part for part in (make, model, str(year) if year else None) if part)


# --- Database error mapping ---------------------------------------------------------------------


@contextlib.contextmanager
def vehicle_errors() -> Generator[None]:
    """Turn the database's own lifecycle and uniqueness checks into API errors."""
    try:
        yield
    except IntegrityError as exc:
        constraint = getattr(getattr(exc.orig, "diag", None), "constraint_name", None)
        if constraint == "vehicles_vin_active_idx":
            raise AppError(
                "VEHICLE_VIN_DUPLICATE", "A vehicle with this VIN is already in stock", status_code=409
            ) from exc
        if constraint == "sales_one_posted_per_vehicle_idx":
            raise AppError("VEHICLE_ALREADY_SOLD", "This vehicle has already been sold", status_code=409) from exc
        if constraint == "reservations_one_active_idx":
            raise AppError("VEHICLE_RESERVED", "This vehicle is already reserved", status_code=409) from exc
        raise
    except DBAPIError as exc:
        if getattr(exc.orig, "sqlstate", None) == "SR020":
            detail = getattr(getattr(exc.orig, "diag", None), "message_detail", None) or ">"
            from_status, _, to_status = detail.partition(">")
            raise AppError(
                "VEHICLE_INVALID_TRANSITION",
                "The vehicle cannot move to this status",
                status_code=409,
                details={"from": from_status, "to": to_status},
            ) from exc
        raise


def _set_reason(conn: Connection, reason: str | None) -> None:
    conn.execute(text("select set_config('app.change_reason', :reason, true)"), {"reason": reason or ""})


def set_status(conn: Connection, vehicle_id: UUID, status: str, reason: str | None = None) -> None:
    """Move a vehicle through the lifecycle; the database rejects illegal moves (SR020)."""
    _set_reason(conn, reason)
    with vehicle_errors():
        conn.execute(
            text("update public.vehicles set status = :status where id = :id"), {"status": status, "id": vehicle_id}
        )
    _set_reason(conn, None)


# --- Locations --------------------------------------------------------------------------------------

_LOCATIONS = """
    select id, type, name_ar, name_en, is_default, archived_at is not null as archived from public.locations
"""


def list_locations(conn: Connection, include_archived: bool = False) -> list[LocationOut]:
    where = "" if include_archived else " where archived_at is null"
    rows = conn.execute(text(_LOCATIONS + where + " order by is_default desc, type, name_ar")).mappings()
    return [LocationOut.model_validate(dict(row)) for row in rows]


def _get_location(conn: Connection, location_id: UUID) -> LocationOut:
    row = conn.execute(text(_LOCATIONS + " where id = :id"), {"id": location_id}).mappings().first()
    if row is None:
        raise not_found("location")
    return LocationOut.model_validate(dict(row))


def create_location(conn: Connection, payload: LocationIn) -> LocationOut:
    if payload.is_default:
        conn.execute(text("update public.locations set is_default = false where is_default"))
    new_id = conn.execute(
        text(
            "insert into public.locations (tenant_id, type, name_ar, name_en, is_default) "
            "values (private.current_tenant_id(), :type, :name_ar, :name_en, :is_default) returning id"
        ),
        payload.model_dump(),
    ).scalar_one()
    return _get_location(conn, new_id)


def update_location(conn: Connection, location_id: UUID, changes: LocationUpdate) -> LocationOut:
    current = _get_location(conn, location_id)
    if changes.archived is True:
        in_use = conn.execute(
            text("select count(*) from public.vehicles where current_location_id = :id and archived_at is null"),
            {"id": location_id},
        ).scalar_one()
        if in_use or current.is_default:
            raise AppError("LOCATION_IN_USE", "Vehicles are still at this location", status_code=409)
    if changes.is_default:
        conn.execute(
            text("update public.locations set is_default = false where is_default and id <> :id"), {"id": location_id}
        )
    values: dict[str, Any] = changes.model_dump(exclude_unset=True, exclude={"archived"})
    if changes.archived is not None:
        conn.execute(
            text("update public.locations set archived_at = case when :archived then now() end where id = :id"),
            {"archived": changes.archived, "id": location_id},
        )
    if values:
        assignments = ", ".join(f"{column} = :{column}" for column in values)  # keys from a StrictModel
        conn.execute(text(f"update public.locations set {assignments} where id = :id"), {**values, "id": location_id})  # noqa: S608
    return _get_location(conn, location_id)


def _location_of_type(conn: Connection, location_type: str) -> UUID | None:
    return conn.execute(
        text(
            "select id from public.locations where archived_at is null and type = :type "
            "order by is_default desc, created_at limit 1"
        ),
        {"type": location_type},
    ).scalar_one_or_none()


def default_location(conn: Connection) -> UUID | None:
    return conn.execute(
        text(
            "select id from public.locations where archived_at is null "
            "order by is_default desc, (type = 'BRANCH_YARD') desc, created_at limit 1"
        )
    ).scalar_one_or_none()


def _active_location(conn: Connection, location_id: UUID) -> UUID:
    row = conn.execute(
        text("select id from public.locations where id = :id and archived_at is null"), {"id": location_id}
    ).first()
    if row is None:
        raise AppError("LOCATION_INVALID", "Unknown or archived location", status_code=422)
    return location_id


# --- Vehicle records ------------------------------------------------------------------------------------


@dataclass(frozen=True)
class VehicleRef:
    id: UUID
    stock_no: str
    make: str
    model: str
    year: int | None
    status: str
    ownership_type: str
    asking_price: Decimal | None
    stock_date: date | None

    @property
    def label(self) -> str:
        return vehicle_label(self.make, self.model, self.year)


def vehicle_ref(conn: Connection, vehicle_id: UUID, *, lock: bool = False) -> VehicleRef:
    row = (
        conn.execute(
            text(
                "select id, stock_no, make, model, year, status, ownership_type, asking_price, stock_date "
                "from public.vehicles where id = :id" + (" for update" if lock else "")
            ),
            {"id": vehicle_id},
        )
        .mappings()
        .first()
    )
    if row is None:
        raise not_found("vehicle")
    return VehicleRef(**row)


def _check_vin_free(conn: Connection, vin: str | None, own_id: UUID | None) -> None:
    if not vin:
        return
    normalized = "".join(ch for ch in vin.upper() if ch.isalnum())
    if not 4 <= len(normalized) <= 20:
        raise AppError("VIN_INVALID", "The chassis number looks wrong", status_code=422, details={"vin": vin})
    existing = conn.execute(
        text(
            "select id, stock_no from public.vehicles where vin_normalized = :vin and archived_at is null "
            "and status not in ('DELIVERED', 'RETURNED_TO_OWNER') and (cast(:own as uuid) is null or id <> :own)"
        ),
        {"vin": normalized, "own": own_id},
    ).first()
    if existing is not None:
        raise AppError(
            "VEHICLE_VIN_DUPLICATE",
            "A vehicle with this VIN is already in stock",
            status_code=409,
            details={"vehicle_id": str(existing.id), "stock_no": existing.stock_no},
        )


def create_vehicle(
    conn: Connection, payload: VehicleIn, *, acquisition_source: str | None = None, reason: str | None = None
) -> UUID:
    _check_vin_free(conn, payload.vin, None)
    location_id = _active_location(conn, payload.current_location_id) if payload.current_location_id else None
    values = payload.model_dump(exclude={"current_location_id", "acquisition_source"})
    values["acquisition_source"] = acquisition_source or payload.acquisition_source
    values["current_location_id"] = location_id or default_location(conn)
    columns = list(values)
    _set_reason(conn, reason)
    with vehicle_errors():
        vehicle_id: UUID = conn.execute(
            text(
                f"insert into public.vehicles (tenant_id, {', '.join(columns)}) "  # noqa: S608 - keys from a StrictModel
                f"values (private.current_tenant_id(), {', '.join(':' + c for c in columns)}) returning id"
            ),
            values,
        ).scalar_one()
    _set_reason(conn, None)
    return vehicle_id


def update_vehicle(conn: Connection, vehicle_id: UUID, changes: VehicleUpdate) -> None:
    current = vehicle_ref(conn, vehicle_id, lock=True)
    if current.status == "ARCHIVED":
        raise AppError("VEHICLE_ARCHIVED", "The vehicle is archived", status_code=409)
    values = changes.model_dump(exclude_unset=True)
    for required in ("make", "model"):
        if required in values and not values[required]:
            raise AppError("VALIDATION_ERROR", f"{required} is required", status_code=422)
    if "vin" in values:
        _check_vin_free(conn, values["vin"], vehicle_id)
    if values:
        assignments = ", ".join(f"{column} = :{column}" for column in values)  # keys from a StrictModel
        with vehicle_errors():
            conn.execute(text(f"update public.vehicles set {assignments} where id = :id"), {**values, "id": vehicle_id})  # noqa: S608


def change_status(conn: Connection, vehicle_id: UUID, status: VehicleStatus, reason: str | None) -> None:
    current = vehicle_ref(conn, vehicle_id, lock=True)
    if (current.status, status) not in MANUAL_TRANSITIONS:
        raise AppError(
            "VEHICLE_INVALID_TRANSITION",
            "The vehicle cannot move to this status from here",
            status_code=409,
            details={"from": current.status, "to": status},
        )
    if status == "ARCHIVED" and inventory_cost(conn, vehicle_id) != 0:
        # Money must not disappear with an archived record (like D-53).
        raise AppError("VEHICLE_HAS_COST", "A vehicle with recorded cost cannot be archived", status_code=409)
    set_status(conn, vehicle_id, status, reason)
    if status == "DELIVERED":
        with_customer = _location_of_type(conn, "CUSTOMER")
        if with_customer is not None:
            move(conn, vehicle_id, with_customer, reason)


def move(conn: Connection, vehicle_id: UUID, location_id: UUID, reason: str | None) -> None:
    current = vehicle_ref(conn, vehicle_id, lock=True)
    if current.status == "ARCHIVED":
        raise AppError("VEHICLE_ARCHIVED", "The vehicle is archived", status_code=409)
    _active_location(conn, location_id)
    _set_reason(conn, reason)
    conn.execute(
        text("update public.vehicles set current_location_id = :location where id = :id"),
        {"location": location_id, "id": vehicle_id},
    )
    _set_reason(conn, None)


# --- Cost and profit (derived, D-26) ------------------------------------------------------------------------

_COST_TOTALS = text(
    """
    select l.vehicle_id,
           coalesce(sum(l.debit - l.credit) filter (where a.system_key = 'VEHICLE_INVENTORY'), 0) as inventory,
           coalesce(sum(l.debit - l.credit) filter (where a.system_key = 'COST_OF_VEHICLES_SOLD'), 0) as cogs,
           coalesce(sum(l.credit - l.debit) filter (where a.system_key = 'VEHICLE_SALES'), 0) as sales
      from public.journal_lines l
      join public.ledger_accounts a on a.id = l.ledger_account_id
     where l.vehicle_id = any(:ids)
       and a.system_key in ('VEHICLE_INVENTORY', 'COST_OF_VEHICLES_SOLD', 'VEHICLE_SALES')
     group by l.vehicle_id
    """
)


@dataclass(frozen=True)
class CostTotals:
    inventory: Decimal
    cogs: Decimal
    sales: Decimal

    @property
    def total_cost(self) -> Decimal:
        # In stock: the inventory balance; once sold: what moved to cost of sales.
        return self.inventory + self.cogs


def cost_totals(conn: Connection, vehicle_ids: list[UUID]) -> dict[UUID, CostTotals]:
    totals = {vid: CostTotals(ZERO, ZERO, ZERO) for vid in vehicle_ids}
    for row in conn.execute(_COST_TOTALS, {"ids": vehicle_ids}):
        totals[row.vehicle_id] = CostTotals(Decimal(row.inventory), Decimal(row.cogs), Decimal(row.sales))
    return totals


def inventory_cost(conn: Connection, vehicle_id: UUID) -> Decimal:
    return cost_totals(conn, [vehicle_id])[vehicle_id].inventory


def missing_categories(conn: Connection, vehicle_ids: list[UUID], language: str = "ar") -> dict[UUID, list[str]]:
    """Expected cost categories (tenant checklist) with no posted expense yet (SPEC §4.3)."""
    rows = conn.execute(
        text(
            """
            select v.id as vehicle_id, ec.name_ar, ec.name_en
              from public.vehicles v
              cross join public.tenant_settings s
              join public.expense_categories ec
                on ec.kind = 'VEHICLE' and ec.archived_at is null and ec.code = any(s.expected_cost_categories)
             where v.id = any(:ids) and v.status not in ('DRAFT', 'ARCHIVED')
               and not exists (select 1 from public.vehicle_expenses e
                                where e.vehicle_id = v.id and e.category_id = ec.id and e.status = 'POSTED')
             order by ec.sort_order
            """
        ),
        {"ids": vehicle_ids},
    )
    missing: dict[UUID, list[str]] = {vid: [] for vid in vehicle_ids}
    for row in rows:
        missing[row.vehicle_id].append(row.name_ar if language == "ar" else row.name_en)
    return missing


_COST_LINES = text(
    """
    select e.entry_date, e.entry_no, e.source_type, coalesce(l.memo, e.description) as label,
           l.debit - l.credit as amount, e.reversed_by_id is not null as reversed,
           e.reversal_of_id is not null as is_reversal
      from public.journal_lines l
      join public.journal_entries e on e.id = l.journal_entry_id
      join public.ledger_accounts a on a.id = l.ledger_account_id
     where l.vehicle_id = :id
       and ((a.system_key = 'VEHICLE_INVENTORY' and e.source_type <> 'SALE_COST')
            or (a.system_key = 'COST_OF_VEHICLES_SOLD' and e.source_type = 'VEHICLE_EXPENSE'))
     order by e.entry_date, e.entry_no, l.line_no
    """
)


def _profit(totals: CostTotals, estimate: bool) -> VehicleProfit | None:
    if totals.sales <= 0:
        return None
    gross = totals.sales - totals.cogs
    return VehicleProfit(
        sale_price=totals.sales,
        cost=totals.cogs,
        gross_profit=gross,
        profit_pct=quantize(gross * 100 / totals.sales),
        estimate=estimate,
    )


# --- Days in stock and aging ----------------------------------------------------------------------------


def _thresholds(conn: Connection) -> list[int]:
    return list(conn.execute(text("select aging_thresholds from public.tenant_settings")).scalar_one())


def _days(status: str, stock_date: date | None, sale_date: date | None, today: date) -> int | None:
    if stock_date is None:
        return None
    if status in IN_STOCK:
        return (today - stock_date).days
    if status in ("SOLD", "DELIVERED") and sale_date is not None:
        return (sale_date - stock_date).days
    return None


def _aging(status: str, days: int | None, thresholds: list[int]) -> Aging | None:
    if status not in IN_STOCK or days is None:
        return None
    if days < thresholds[0]:
        return "FRESH"
    if days < thresholds[1]:
        return "AGING"
    if days < thresholds[2]:
        return "OLD"
    return "STALE"


# --- Inventory list ----------------------------------------------------------------------------------------

_SORTS = {
    "stock_date": "v.stock_date nulls last, v.stock_no",
    "-stock_date": "v.stock_date desc nulls last, v.stock_no",
    "price": "v.asking_price nulls last, v.stock_no",
    "-price": "v.asking_price desc nulls last, v.stock_no",
    "make": "v.make, v.model, v.year desc",
    "-created": "v.created_at desc",
}


_VEHICLE_ROWS = """
            select v.id, v.stock_no, v.make, v.model, v.trim, v.year, v.color_ext, v.plate_no, v.vin, v.status,
                   v.ownership_type, lo.name_ar as location_name_ar, lo.name_en as location_name_en, v.asking_price,
                   v.min_price, v.stock_date,
                   (select s.sale_date from public.sales s
                     where s.vehicle_id = v.id and s.status = 'POSTED') as sale_date,
                   (select m.storage_path from public.vehicle_media m
                     where m.vehicle_id = v.id and m.archived_at is null order by m.sort_order, m.created_at limit 1)
                     as photo_path
              from public.vehicles v
              left join public.locations lo on lo.id = v.current_location_id
"""


def list_vehicles(
    conn: Connection,
    storage: Storage,
    *,
    statuses: list[str] | None,
    make: str | None,
    year: int | None,
    location_id: UUID | None,
    ownership_type: str | None,
    q: str | None,
    aging: str | None,
    sort: str,
    page: int,
    page_size: int,
) -> VehiclePage:
    where = """
     where (cast(:statuses as text[]) is null or v.status = any(:statuses))
       and (cast(:make as text) is null or v.make ilike :make)
       and (cast(:year as int) is null or v.year = :year)
       and (cast(:location_id as uuid) is null or v.current_location_id = :location_id)
       and (cast(:ownership as text) is null or v.ownership_type = :ownership)
       and (cast(:q as text) is null or v.stock_no ilike '%' || :q || '%' or v.plate_no ilike '%' || :q || '%'
            or v.vin_normalized like '%' || upper(:q) || '%'
            or concat_ws(' ', v.make, v.model, v.trim) ilike '%' || :q || '%')
    """
    params: dict[str, Any] = {
        "statuses": statuses or None,
        "make": make,
        "year": year,
        "location_id": location_id,
        "ownership": ownership_type,
        "q": q.strip() if q and q.strip() else None,
    }
    info = finance.tenant_info(conn)
    thresholds = _thresholds(conn)
    if aging:
        # Aging is derived from the stock date and the tenant's thresholds.
        bounds = {
            "FRESH": (0, thresholds[0]),
            "AGING": thresholds[0:2],
            "OLD": thresholds[1:3],
            "STALE": (thresholds[2], 100000),
        }
        low, high = bounds.get(aging, (0, 100000))
        where += (
            " and v.status in ('IN_PREPARATION', 'AVAILABLE', 'RESERVED', 'AT_OTHER_SHOWROOM')"
            " and v.stock_date is not null and (cast(:today as date) - v.stock_date) >= :low"
            " and (cast(:today as date) - v.stock_date) < :high"
        )
        params.update(today=info.today, low=low, high=high)
    total = conn.execute(text("select count(*) from public.vehicles v" + where), params).scalar_one()  # noqa: S608 - fixed SQL fragments, values are bound
    order = _SORTS.get(sort, _SORTS["-created"])
    rows = conn.execute(
        text(_VEHICLE_ROWS + where + f" order by {order} limit :limit offset :offset"),
        {**params, "limit": page_size, "offset": (page - 1) * page_size},
    ).fetchall()
    ids = [row.id for row in rows]
    totals = cost_totals(conn, ids)
    missing = missing_categories(conn, ids)
    photos = storage.view_urls(MEDIA_BUCKET, [row.photo_path for row in rows if row.photo_path])
    items = []
    for row in rows:
        days = _days(row.status, row.stock_date, row.sale_date, info.today)
        items.append(
            VehicleRow(
                id=row.id,
                stock_no=row.stock_no,
                make=row.make,
                model=row.model,
                trim=row.trim,
                year=row.year,
                color_ext=row.color_ext,
                plate_no=row.plate_no,
                vin=row.vin,
                status=row.status,
                ownership_type=row.ownership_type,
                location_name_ar=row.location_name_ar,
                location_name_en=row.location_name_en,
                asking_price=row.asking_price,
                stock_date=row.stock_date,
                days_in_stock=days,
                aging=_aging(row.status, days, thresholds),
                photo_url=photos.get(row.photo_path) if row.photo_path else None,
                min_price=row.min_price,
                total_cost=totals[row.id].total_cost,
                cost_complete=not missing[row.id],
            )
        )
    return VehiclePage(items=items, page=page, page_size=page_size, total=total)


def search(conn: Connection, q: str, limit: int = 6) -> list[VehicleHit]:
    """Quick search: stock number, plate, make/model, or the last digits of the VIN (SPEC §4.3)."""
    rows = conn.execute(
        text(
            """
            select id, stock_no, make, model, year, plate_no, vin, status
              from public.vehicles
             where archived_at is null
               and (stock_no ilike '%' || :q || '%' or plate_no ilike '%' || :q || '%'
                    or vin_normalized like '%' || upper(regexp_replace(:q, '[^A-Za-z0-9]', '', 'g')) || '%'
                    or concat_ws(' ', make, model, trim) ilike '%' || :q || '%')
             order by (status in ('AVAILABLE', 'RESERVED', 'IN_PREPARATION')) desc,
                      (vin_normalized like '%' || upper(:q)) desc, created_at desc
             limit :limit
            """
        ),
        {"q": q, "limit": limit},
    )
    return [
        VehicleHit(
            id=row.id,
            stock_no=row.stock_no,
            label=vehicle_label(row.make, row.model, row.year),
            plate_no=row.plate_no,
            vin=row.vin,
            status=row.status,
        )
        for row in rows
    ]


# --- Vehicle file ------------------------------------------------------------------------------------------


def get_detail(conn: Connection, vehicle_id: UUID, storage: Storage, *, can_view_cost: bool) -> VehicleDetail:
    info = finance.tenant_info(conn)
    row = conn.execute(
        text(
            """
            select v.*, lo.name_ar as location_name_ar, lo.name_en as location_name_en
              from public.vehicles v left join public.locations lo on lo.id = v.current_location_id
             where v.id = :id
            """
        ),
        {"id": vehicle_id},
    ).first()
    if row is None:
        raise not_found("vehicle")
    v = row._mapping

    status_history = [
        StatusChange.model_validate(dict(r))
        for r in conn.execute(
            text(
                "select from_status, to_status, changed_at, reason from public.vehicle_status_history "
                "where vehicle_id = :id order by changed_at, id"
            ),
            {"id": vehicle_id},
        ).mappings()
    ]
    location_history = [
        LocationChange.model_validate(dict(r))
        for r in conn.execute(
            text(
                """
                select fl.name_ar as from_name_ar, tl.name_ar as to_name_ar, h.moved_at, h.reason
                  from public.vehicle_location_history h
                  left join public.locations fl on fl.id = h.from_location_id
                  left join public.locations tl on tl.id = h.to_location_id
                 where h.vehicle_id = :id order by h.moved_at, h.id
                """
            ),
            {"id": vehicle_id},
        ).mappings()
    ]
    price_history = [
        PriceChange.model_validate(dict(r))
        for r in conn.execute(
            text(
                "select asking_price, min_price, changed_at from public.vehicle_price_history "
                "where vehicle_id = :id order by changed_at, id"
            ),
            {"id": vehicle_id},
        ).mappings()
    ]
    media_rows = conn.execute(
        text(
            "select id, storage_path, sort_order from public.vehicle_media "
            "where vehicle_id = :id and archived_at is null order by sort_order, created_at"
        ),
        {"id": vehicle_id},
    ).fetchall()
    urls = storage.view_urls(MEDIA_BUCKET, [m.storage_path for m in media_rows])
    media = [MediaOut(id=m.id, url=urls.get(m.storage_path), sort_order=m.sort_order) for m in media_rows]

    reservation_row = (
        conn.execute(
            text(
                """
            select r.id, r.customer_id, c.name as customer_name, r.deposit_amount, r.reservation_date, r.expires_on
              from public.reservations r join public.customers c on c.id = r.customer_id
             where r.vehicle_id = :id and r.status = 'ACTIVE'
            """
            ),
            {"id": vehicle_id},
        )
        .mappings()
        .first()
    )
    reservation = None
    if reservation_row is not None:
        expires_on = reservation_row["expires_on"]
        reservation = ActiveReservation.model_validate(
            {**reservation_row, "expired": expires_on is not None and expires_on < info.today}
        )
    sale_row = (
        conn.execute(
            text(
                """
            select s.id, s.sale_no, s.sale_date, s.buyer_customer_id, c.name as buyer_name, s.sale_price, s.invoice_no
              from public.sales s join public.customers c on c.id = s.buyer_customer_id
             where s.vehicle_id = :id and s.status = 'POSTED'
            """
            ),
            {"id": vehicle_id},
        )
        .mappings()
        .first()
    )
    sale = VehicleSaleInfo.model_validate(dict(sale_row)) if sale_row is not None else None

    thresholds = _thresholds(conn)
    days = _days(v["status"], v["stock_date"], sale.sale_date if sale else None, info.today)
    last_change = v["last_price_change_at"]
    detail = VehicleDetail(
        id=v["id"],
        stock_no=v["stock_no"],
        vin=v["vin"],
        plate_no=v["plate_no"],
        make=v["make"],
        model=v["model"],
        trim=v["trim"],
        year=v["year"],
        color_ext=v["color_ext"],
        color_int=v["color_int"],
        body_type=v["body_type"],
        transmission=v["transmission"],
        fuel=v["fuel"],
        engine_cc=v["engine_cc"],
        mileage_km=v["mileage_km"],
        license_expiry=v["license_expiry"],
        license_governorate=v["license_governorate"],
        ownership_type=v["ownership_type"],
        acquisition_source=v["acquisition_source"],
        status=v["status"],
        current_location_id=v["current_location_id"],
        location_name_ar=v["location_name_ar"],
        location_name_en=v["location_name_en"],
        asking_price=v["asking_price"],
        stock_date=v["stock_date"],
        days_in_stock=days,
        aging=_aging(v["status"], days, thresholds),
        days_since_price_change=(info.today - last_change.date()).days if last_change else None,
        notes=v["notes"],
        archived=v["archived_at"] is not None,
        status_history=status_history,
        location_history=location_history,
        price_history=price_history,
        media=media,
        documents=list_documents(conn, "VEHICLE", vehicle_id, can_view_cost=can_view_cost),
        reservation=reservation,
        sale=sale,
        min_price=v["min_price"],
    )
    if can_view_cost:
        # Cost data is only computed for users who may see it.
        totals = cost_totals(conn, [vehicle_id])[vehicle_id]
        missing = missing_categories(conn, [vehicle_id])[vehicle_id]
        lines = [CostLine.model_validate(dict(r)) for r in conn.execute(_COST_LINES, {"id": vehicle_id}).mappings()]
        detail.cost = VehicleCost(
            total_cost=totals.total_cost, lines=lines, cost_complete=not missing, missing_categories=missing
        )
        detail.profit = _profit(totals, estimate=bool(missing))
        detail.purchase = purchase_summary(conn, vehicle_id)
    return detail


def purchase_summary(conn: Connection, vehicle_id: UUID) -> PurchaseSummary | None:
    row = (
        conn.execute(
            text(
                """
            select p.id, p.source, p.seller_customer_id, c.name as seller_name, p.purchase_date, p.price,
                   p.deferred_amount, je.entry_no,
                   coalesce((select sum(l.credit - l.debit)
                               from public.journal_lines l join public.ledger_accounts a on a.id = l.ledger_account_id
                              where a.system_key = 'SELLER_PAYABLE' and l.vehicle_id = p.vehicle_id
                                and l.customer_id = p.seller_customer_id), 0) as outstanding
              from public.vehicle_purchases p
              join public.customers c on c.id = p.seller_customer_id
              join public.journal_entries je on je.id = p.journal_entry_id
             where p.vehicle_id = :id and p.status = 'POSTED'
            """
            ),
            {"id": vehicle_id},
        )
        .mappings()
        .first()
    )
    return PurchaseSummary.model_validate(dict(row)) if row else None


# --- Purchase (rules 6, 7) ------------------------------------------------------------------------------------


@dataclass(frozen=True)
class _PurchasePlan:
    draft: EntryDraft
    vehicle: VehicleRef
    seller_name: str
    legs: list[tuple[finance.ActiveCashAccount, Decimal]]
    deferred: Decimal


def _owned_vehicle(vehicle: VehicleRef) -> None:
    if vehicle.ownership_type != "OWNED":
        # Consigned-in cars follow the consignment rules (Phase 6).
        raise AppError("VEHICLE_NOT_OWNED", "This operation is for owned vehicles only", status_code=422)


def _plan_purchase(
    conn: Connection, info: finance.TenantInfo, vehicle: VehicleRef, payload: PurchaseIn
) -> _PurchasePlan:
    finance.check_entry_date(info, payload.purchase_date)
    _owned_vehicle(vehicle)
    if vehicle.status not in ("DRAFT", "IN_PREPARATION", "AVAILABLE"):
        raise AppError(
            "VEHICLE_INVALID_TRANSITION",
            "A purchase can only be recorded for a car that is not yet sold",
            status_code=409,
            details={"from": vehicle.status},
        )
    if purchase_summary(conn, vehicle.id) is not None:
        raise AppError("VEHICLE_ALREADY_PURCHASED", "The purchase of this vehicle is already recorded", status_code=409)
    seller = customers.active_customer(conn, payload.seller_customer_id)
    legs = [(finance.active_cash_account(conn, leg.cash_account_id), leg.amount) for leg in payload.payments]
    paid = sum((amount for _, amount in legs), ZERO)
    if paid > payload.price:
        raise AppError(
            "PURCHASE_PAYMENTS_EXCEED_PRICE",
            "The payments are more than the purchase price",
            status_code=422,
            details={"price": f"{payload.price:.2f}", "paid": f"{paid:.2f}"},
        )
    draft = rules.vehicle_purchase(
        entry_date=payload.purchase_date,
        vehicle_id=vehicle.id,
        seller_id=seller.id,
        price=payload.price,
        payments=[(account.ref, amount) for account, amount in legs],
        description=payload.notes or f"شراء {vehicle.label} ({vehicle.stock_no}) من {seller.name}",
        source_id=None,
    )
    return _PurchasePlan(
        draft=draft, vehicle=vehicle, seller_name=seller.name, legs=legs, deferred=payload.price - paid
    )


def preview_purchase(conn: Connection, vehicle_id: UUID, payload: PurchaseIn, *, with_lines: bool) -> Preview:
    info = finance.tenant_info(conn)
    plan = _plan_purchase(conn, info, vehicle_ref(conn, vehicle_id), payload)
    finance.ensure_period_open(conn, payload.purchase_date)
    warnings = finance.check_cash(conn, info, plan.draft.cash_effects(), lock=False)
    price_ar = format_money(payload.price, info.currency, "ar")
    price_en = format_money(payload.price, info.currency, "en")
    paid_ar = "، ".join(
        f"{format_money(amount, info.currency, 'ar')} من «{account.name_ar}»" for account, amount in plan.legs
    )
    paid_en = ", ".join(
        f"{format_money(amount, info.currency, 'en')} from “{account.name_en}”" for account, amount in plan.legs
    )
    summary_ar = f"سيتم تسجيل شراء {plan.vehicle.label} من {plan.seller_name} بسعر {price_ar}"
    summary_en = f"The purchase of {plan.vehicle.label} from {plan.seller_name} for {price_en} will be recorded"
    if plan.legs:
        summary_ar += f"، يُدفع منها {paid_ar}"
        summary_en += f"; paid now: {paid_en}"
    if plan.deferred > 0:
        summary_ar += f"، ويتبقى للبائع {format_money(plan.deferred, info.currency, 'ar')}"
        summary_en += f"; still owed to the seller: {format_money(plan.deferred, info.currency, 'en')}"
    return Preview(
        summary_ar=f"{summary_ar} بتاريخ {ltr(payload.purchase_date.isoformat())}. يصبح هذا المبلغ أساس تكلفة السيارة.",
        summary_en=f"{summary_en}, on {payload.purchase_date.isoformat()}. This becomes the car's starting cost.",
        effects=[
            PreviewEffect(direction="OUT", label_ar=account.name_ar, label_en=account.name_en, amount=amount)
            for account, amount in plan.legs
        ],
        warnings=warnings,
        lines=finance.preview_lines(conn, plan.draft) if with_lines else None,
    )


def record_purchase(conn: Connection, vehicle_id: UUID, payload: PurchaseIn) -> PostingResult[PurchaseOut]:
    info = finance.tenant_info(conn)
    vehicle = vehicle_ref(conn, vehicle_id, lock=True)
    plan = _plan_purchase(conn, info, vehicle, payload)
    warnings = finance.check_cash(conn, info, plan.draft.cash_effects(), lock=True)
    purchase_id = uuid4()
    posted = engine.post(conn, replace(plan.draft, source_id=purchase_id))
    conn.execute(
        text(
            """
            insert into public.vehicle_purchases
              (id, tenant_id, vehicle_id, seller_customer_id, purchase_date, price, deferred_amount, notes,
               journal_entry_id)
            values (:id, private.current_tenant_id(), :vehicle_id, :seller, :purchase_date, :price, :deferred, :notes,
                    :entry)
            """
        ),
        {
            "id": purchase_id,
            "vehicle_id": vehicle_id,
            "seller": payload.seller_customer_id,
            "purchase_date": payload.purchase_date,
            "price": payload.price,
            "deferred": plan.deferred,
            "notes": payload.notes,
            "entry": posted.id,
        },
    )
    for leg in payload.payments:
        conn.execute(
            text(
                "insert into public.purchase_payments (tenant_id, purchase_id, cash_account_id, amount) "
                "values (private.current_tenant_id(), :purchase, :cash, :amount)"
            ),
            {"purchase": purchase_id, "cash": leg.cash_account_id, "amount": leg.amount},
        )
    customers.flag(conn, payload.seller_customer_id, seller=True)
    # Days in stock start at the purchase date (Q-24 default).
    conn.execute(
        text("update public.vehicles set stock_date = :d where id = :id"),
        {"d": payload.purchase_date, "id": vehicle_id},
    )
    if vehicle.status == "DRAFT":
        set_status(conn, vehicle_id, "IN_PREPARATION", "شراء")
    if payload.ready_for_sale and vehicle.status in ("DRAFT", "IN_PREPARATION"):
        set_status(conn, vehicle_id, "AVAILABLE", "جاهزة للبيع")
    return PostingResult[PurchaseOut](
        document=PurchaseOut(
            id=purchase_id,
            vehicle_id=vehicle_id,
            seller_customer_id=payload.seller_customer_id,
            seller_name=plan.seller_name,
            purchase_date=payload.purchase_date,
            price=payload.price,
            deferred_amount=plan.deferred,
            status="POSTED",
            entry_no=posted.entry_no,
        ),
        journal_entries=[EntryRef(id=posted.id, entry_no=posted.entry_no)],
        warnings=warnings,
    )


# --- Paying the seller later (rule 8) ---------------------------------------------------------------------------


def _plan_seller_payment(
    conn: Connection, info: finance.TenantInfo, vehicle: VehicleRef, payload: SellerPaymentIn
) -> tuple[EntryDraft, finance.ActiveCashAccount, PurchaseSummary]:
    finance.check_entry_date(info, payload.payment_date)
    purchase = purchase_summary(conn, vehicle.id)
    if purchase is None or purchase.outstanding <= 0:
        raise AppError("NOTHING_OWED", "Nothing is owed to the seller of this car", status_code=422)
    if payload.amount > purchase.outstanding:
        raise AppError(
            "PAYMENT_EXCEEDS_BALANCE",
            "The payment is more than the showroom owes",
            status_code=422,
            details={"outstanding": f"{purchase.outstanding:.2f}"},
        )
    cash = finance.active_cash_account(conn, payload.cash_account_id)
    draft = rules.seller_payment(
        entry_date=payload.payment_date,
        vehicle_id=vehicle.id,
        seller_id=purchase.seller_customer_id,
        amount=payload.amount,
        paid_from=cash.ref,
        description=payload.notes
        or f"سداد باقي ثمن {vehicle.label} ({vehicle.stock_no}) للبائع {purchase.seller_name}",
        source_id=None,
    )
    return draft, cash, purchase


def preview_seller_payment(
    conn: Connection, vehicle_id: UUID, payload: SellerPaymentIn, *, with_lines: bool
) -> Preview:
    info = finance.tenant_info(conn)
    vehicle = vehicle_ref(conn, vehicle_id)
    draft, cash, purchase = _plan_seller_payment(conn, info, vehicle, payload)
    finance.ensure_period_open(conn, payload.payment_date)
    warnings = finance.check_cash(conn, info, draft.cash_effects(), lock=False)
    remaining = purchase.outstanding - payload.amount
    return Preview(
        summary_ar=(
            f"سيتم دفع {format_money(payload.amount, info.currency, 'ar')} من «{cash.name_ar}» للبائع "
            f"{purchase.seller_name} عن {vehicle.label}. المتبقي له: {format_money(remaining, info.currency, 'ar')}."
        ),
        summary_en=(
            f"{format_money(payload.amount, info.currency, 'en')} will be paid from “{cash.name_en}” to the seller "
            f"{purchase.seller_name} for {vehicle.label}. Still owed: {format_money(remaining, info.currency, 'en')}."
        ),
        effects=[PreviewEffect(direction="OUT", label_ar=cash.name_ar, label_en=cash.name_en, amount=payload.amount)],
        warnings=warnings,
        lines=finance.preview_lines(conn, draft) if with_lines else None,
    )


def record_seller_payment(
    conn: Connection, vehicle_id: UUID, payload: SellerPaymentIn
) -> PostingResult[SellerPaymentOut]:
    info = finance.tenant_info(conn)
    vehicle = vehicle_ref(conn, vehicle_id, lock=True)
    draft, _, purchase = _plan_seller_payment(conn, info, vehicle, payload)
    warnings = finance.check_cash(conn, info, draft.cash_effects(), lock=True)
    document_id = uuid4()
    posted = engine.post(conn, replace(draft, source_id=document_id))
    conn.execute(
        text(
            """
            insert into public.seller_payments
              (id, tenant_id, purchase_id, payment_date, amount, cash_account_id, notes, journal_entry_id)
            values (:id, private.current_tenant_id(), :purchase, :payment_date, :amount, :cash_account_id, :notes,
                    :entry)
            """
        ),
        {**payload.model_dump(), "id": document_id, "purchase": purchase.id, "entry": posted.id},
    )
    return PostingResult[SellerPaymentOut](
        document=SellerPaymentOut(
            id=document_id,
            vehicle_id=vehicle_id,
            payment_date=payload.payment_date,
            amount=payload.amount,
            cash_account_id=payload.cash_account_id,
            status="POSTED",
            entry_no=posted.entry_no,
        ),
        journal_entries=[EntryRef(id=posted.id, entry_no=posted.entry_no)],
        warnings=warnings,
    )


# --- Vehicle expenses (rules 9, 30, 31; P-04) ---------------------------------------------------------------------


@dataclass(frozen=True)
class _ExpensePlan:
    draft: EntryDraft
    vehicle: VehicleRef
    category_ar: str
    category_en: str
    sold: bool
    cash: finance.ActiveCashAccount | None
    payer_ar: str | None
    payer_en: str | None


def _plan_expense(
    conn: Connection, info: finance.TenantInfo, vehicle: VehicleRef, payload: VehicleExpenseIn
) -> _ExpensePlan:
    finance.check_entry_date(info, payload.expense_date)
    _owned_vehicle(vehicle)
    if vehicle.status in ("ARCHIVED", "RETURNED_TO_OWNER"):
        raise AppError("VEHICLE_ARCHIVED", "The vehicle is no longer with the showroom", status_code=409)
    category = conn.execute(
        text("select id, kind, name_ar, name_en from public.expense_categories where id = :id and archived_at is null"),
        {"id": payload.category_id},
    ).first()
    if category is None or category.kind != "VEHICLE":
        raise AppError("CATEGORY_INVALID", "Choose an active vehicle expense category", status_code=422)
    sold = vehicle.status in ("SOLD", "DELIVERED")

    funding: rules.ExpenseFunding
    cash = None
    payer_ar = payer_en = None
    if payload.funding == "CASH_ACCOUNT" and payload.cash_account_id is not None:
        cash = finance.active_cash_account(conn, payload.cash_account_id)
        funding = rules.CashFunding(cash.ref)
    elif payload.funding == "SUPPLIER_CREDIT" and payload.supplier_id is not None:
        supplier = suppliers.active_supplier(conn, payload.supplier_id)
        funding = rules.SupplierFunding(supplier.id)
        payer_ar = payer_en = supplier.name
    elif payload.paid_by_partner_id is not None and payload.partner_funding_mode is not None:
        partner = conn.execute(
            text("select id, name_ar, name_en from public.partners where id = :id and archived_at is null"),
            {"id": payload.paid_by_partner_id},
        ).first()
        if partner is None:
            raise AppError("PARTNER_INVALID", "Unknown or archived partner", status_code=422)
        funding = rules.PartnerFunding(partner.id, payload.partner_funding_mode)
        payer_ar, payer_en = partner.name_ar, partner.name_en or partner.name_ar
    else:  # guarded by the model validator
        raise AppError("VALIDATION_ERROR", "Choose how the expense was paid", status_code=422)

    draft = rules.vehicle_expense(
        entry_date=payload.expense_date,
        vehicle_id=vehicle.id,
        amount=payload.amount,
        category_label=category.name_ar,
        sold=sold,
        funding=funding,
        description=payload.description or f"{category.name_ar} — {vehicle.label} ({vehicle.stock_no})",
        source_id=None,
    )
    return _ExpensePlan(
        draft=draft,
        vehicle=vehicle,
        category_ar=category.name_ar,
        category_en=category.name_en,
        sold=sold,
        cash=cash,
        payer_ar=payer_ar,
        payer_en=payer_en,
    )


def preview_expense(conn: Connection, vehicle_id: UUID, payload: VehicleExpenseIn, *, with_lines: bool) -> Preview:
    info = finance.tenant_info(conn)
    plan = _plan_expense(conn, info, vehicle_ref(conn, vehicle_id), payload)
    finance.ensure_period_open(conn, payload.expense_date)
    warnings = finance.check_cash(conn, info, plan.draft.cash_effects(), lock=False)
    amount_ar = format_money(payload.amount, info.currency, "ar")
    amount_en = format_money(payload.amount, info.currency, "en")
    if plan.cash is not None:
        how_ar, how_en = f"تُدفع من «{plan.cash.name_ar}»", f"paid from “{plan.cash.name_en}”"
    elif payload.funding == "SUPPLIER_CREDIT":
        how_ar, how_en = f"على الحساب للمورد {plan.payer_ar}", f"on credit from {plan.payer_en}"
    elif payload.partner_funding_mode == "LOAN":
        how_ar = f"دفعها الشريك {plan.payer_ar} من ماله الخاص وتُسجَّل كقرض منه"
        how_en = f"paid personally by partner {plan.payer_en}, recorded as a loan from them"
    else:
        how_ar = f"دفعها الشريك {plan.payer_ar} من ماله الخاص وتُضاف لحسابه الجاري"
        how_en = f"paid personally by partner {plan.payer_en}, credited to their current account"
    if plan.sold:
        effect_ar = "السيارة مباعة، فتُحمَّل على تكلفة المبيعات وتُخفض ربحها"
        effect_en = "the car is already sold, so it is charged to cost of sales and lowers its profit"
    else:
        effect_ar, effect_en = "تُضاف إلى تكلفة السيارة", "it is added to the car's cost"
    return Preview(
        summary_ar=(
            f"مصروف «{plan.category_ar}» بقيمة {amount_ar} على {plan.vehicle.label} ({plan.vehicle.stock_no})، "
            f"{how_ar}، بتاريخ {ltr(payload.expense_date.isoformat())}؛ {effect_ar}."
        ),
        summary_en=(
            f"A “{plan.category_en}” expense of {amount_en} on {plan.vehicle.label} ({plan.vehicle.stock_no}), "
            f"{how_en}, on {payload.expense_date.isoformat()}; {effect_en}."
        ),
        effects=(
            [
                PreviewEffect(
                    direction="OUT", label_ar=plan.cash.name_ar, label_en=plan.cash.name_en, amount=payload.amount
                )
            ]
            if plan.cash
            else []
        ),
        warnings=warnings,
        lines=finance.preview_lines(conn, plan.draft) if with_lines else None,
    )


def record_expense(conn: Connection, vehicle_id: UUID, payload: VehicleExpenseIn) -> PostingResult[VehicleExpenseOut]:
    info = finance.tenant_info(conn)
    plan = _plan_expense(conn, info, vehicle_ref(conn, vehicle_id, lock=True), payload)
    warnings = finance.check_cash(conn, info, plan.draft.cash_effects(), lock=True)
    document_id = uuid4()
    posted = engine.post(conn, replace(plan.draft, source_id=document_id))
    conn.execute(
        text(
            """
            insert into public.vehicle_expenses
              (id, tenant_id, vehicle_id, category_id, expense_date, amount, description, funding, cash_account_id,
               supplier_id, paid_by_partner_id, partner_funding_mode, treatment, journal_entry_id)
            values (:id, private.current_tenant_id(), :vehicle_id, :category_id, :expense_date, :amount, :description,
                    :funding, :cash_account_id, :supplier_id, :paid_by_partner_id, :partner_funding_mode, :treatment,
                    :entry)
            """
        ),
        {
            **payload.model_dump(),
            "id": document_id,
            "vehicle_id": vehicle_id,
            "treatment": "COGS" if plan.sold else "CAPITALIZE",
            "entry": posted.id,
        },
    )
    return PostingResult[VehicleExpenseOut](
        document=get_expense(conn, document_id),
        journal_entries=[EntryRef(id=posted.id, entry_no=posted.entry_no)],
        warnings=warnings,
    )


_EXPENSES = """
    select x.id, x.vehicle_id, x.expense_date, x.category_id, ec.code as category_code,
           ec.name_ar as category_name_ar, ec.name_en as category_name_en, x.amount, x.description, x.funding,
           ca.name_ar as cash_account_name_ar, su.name as supplier_name, pa.name_ar as paid_by_partner_name_ar,
           x.treatment, x.status, je.entry_no
      from public.vehicle_expenses x
      join public.expense_categories ec on ec.id = x.category_id
      left join public.cash_accounts ca on ca.id = x.cash_account_id
      left join public.suppliers su on su.id = x.supplier_id
      left join public.partners pa on pa.id = x.paid_by_partner_id
      join public.journal_entries je on je.id = x.journal_entry_id
"""


def get_expense(conn: Connection, expense_id: UUID) -> VehicleExpenseOut:
    row = conn.execute(text(_EXPENSES + " where x.id = :id"), {"id": expense_id}).mappings().first()
    if row is None:
        raise not_found("vehicle expense")
    return VehicleExpenseOut.model_validate(dict(row))


def list_expenses(conn: Connection, vehicle_id: UUID) -> list[VehicleExpenseOut]:
    rows = conn.execute(
        text(_EXPENSES + " where x.vehicle_id = :id order by x.expense_date, je.entry_no"), {"id": vehicle_id}
    ).mappings()
    return [VehicleExpenseOut.model_validate(dict(row)) for row in rows]


# --- Photos ---------------------------------------------------------------------------------------------------------


def media_ticket(conn: Connection, storage: Storage, vehicle_id: UUID, payload: MediaUploadIn) -> UploadTicket:
    vehicle = vehicle_ref(conn, vehicle_id)
    if vehicle.status == "ARCHIVED":
        raise AppError("VEHICLE_ARCHIVED", "The vehicle is archived", status_code=409)
    tenant_id = conn.execute(text("select private.current_tenant_id()")).scalar_one()
    path = f"{tenant_id}/{vehicle_id}/{uuid4()}.{_EXTENSIONS[payload.content_type]}"
    return UploadTicket(upload_url=storage.upload_url(MEDIA_BUCKET, path), storage_path=path)


def register_media(conn: Connection, storage: Storage, vehicle_id: UUID, payload: MediaRegisterIn) -> MediaOut:
    vehicle_ref(conn, vehicle_id)
    tenant_id = conn.execute(text("select private.current_tenant_id()")).scalar_one()
    # Only a file uploaded with this vehicle's ticket can be attached to it.
    if not payload.storage_path.startswith(f"{tenant_id}/{vehicle_id}/") or ".." in payload.storage_path:
        raise AppError("UPLOAD_INVALID", "The file does not belong to this vehicle", status_code=422)
    if not storage.exists(MEDIA_BUCKET, payload.storage_path):
        raise AppError("UPLOAD_MISSING", "The file was not uploaded", status_code=422)
    media_id, sort_order = conn.execute(
        text(
            """
            insert into public.vehicle_media (tenant_id, vehicle_id, storage_path, content_type, size_bytes, sort_order)
            values (private.current_tenant_id(), :vehicle_id, :path, :content_type, :size,
                    coalesce((select max(sort_order) + 1 from public.vehicle_media where vehicle_id = :vehicle_id), 0))
            returning id, sort_order
            """
        ),
        {
            "vehicle_id": vehicle_id,
            "path": payload.storage_path,
            "content_type": payload.content_type,
            "size": payload.size_bytes,
        },
    ).one()
    url = storage.view_urls(MEDIA_BUCKET, [payload.storage_path]).get(payload.storage_path)
    return MediaOut(id=media_id, url=url, sort_order=sort_order)


def archive_media(conn: Connection, vehicle_id: UUID, media_id: UUID) -> None:
    updated = conn.execute(
        text(
            "update public.vehicle_media set archived_at = now() "
            "where id = :id and vehicle_id = :vehicle_id and archived_at is null"
        ),
        {"id": media_id, "vehicle_id": vehicle_id},
    ).rowcount
    if not updated:
        raise not_found("photo")


# --- Documents ------------------------------------------------------------------------------------------------------

_ENTITY_TABLES = {"VEHICLE": "vehicles", "CUSTOMER": "customers", "SALE": "sales", "SUPPLIER": "suppliers"}


def document_sensitivity(doc_type: str) -> str:
    return "COST" if doc_type in _COST_DOCUMENTS else "NORMAL"


def _check_entity(conn: Connection, entity_type: str, entity_id: UUID) -> None:
    table = _ENTITY_TABLES[entity_type]
    exists = conn.execute(
        text(f"select exists (select 1 from public.{table} where id = :id)"),  # noqa: S608 - fixed mapping
        {"id": entity_id},
    ).scalar_one()
    if not exists:
        raise not_found(entity_type.lower())


def document_ticket(conn: Connection, storage: Storage, payload: DocumentUploadIn) -> UploadTicket:
    _check_entity(conn, payload.entity_type, payload.entity_id)
    tenant_id = conn.execute(text("select private.current_tenant_id()")).scalar_one()
    path = (
        f"{tenant_id}/{payload.entity_type.lower()}/{payload.entity_id}/{uuid4()}.{_EXTENSIONS[payload.content_type]}"
    )
    return UploadTicket(upload_url=storage.upload_url(DOCUMENT_BUCKET, path), storage_path=path)


_DOCUMENTS = """
    select id, entity_type, entity_id, doc_type, file_name, content_type, size_bytes, sensitivity, created_at
      from public.documents
"""


def register_document(conn: Connection, storage: Storage, payload: DocumentRegisterIn) -> DocumentOut:
    _check_entity(conn, payload.entity_type, payload.entity_id)
    tenant_id = conn.execute(text("select private.current_tenant_id()")).scalar_one()
    prefix = f"{tenant_id}/{payload.entity_type.lower()}/{payload.entity_id}/"
    if not payload.storage_path.startswith(prefix) or ".." in payload.storage_path:
        raise AppError("UPLOAD_INVALID", "The file does not belong to this record", status_code=422)
    if not storage.exists(DOCUMENT_BUCKET, payload.storage_path):
        raise AppError("UPLOAD_MISSING", "The file was not uploaded", status_code=422)
    document_id = conn.execute(
        text(
            """
            insert into public.documents (tenant_id, entity_type, entity_id, doc_type, storage_path, file_name,
                                          content_type, size_bytes, sensitivity)
            values (private.current_tenant_id(), :entity_type, :entity_id, :doc_type, :storage_path, :file_name,
                    :content_type, :size_bytes, :sensitivity)
            returning id
            """
        ),
        {**payload.model_dump(), "sensitivity": document_sensitivity(payload.doc_type)},
    ).scalar_one()
    row = conn.execute(text(_DOCUMENTS + " where id = :id"), {"id": document_id}).mappings().one()
    return DocumentOut.model_validate(dict(row))


def list_documents(conn: Connection, entity_type: str, entity_id: UUID, *, can_view_cost: bool) -> list[DocumentOut]:
    rows = conn.execute(
        text(
            _DOCUMENTS
            + " where entity_type = :type and entity_id = :id and archived_at is null"
            + ("" if can_view_cost else " and sensitivity = 'NORMAL'")
            + " order by created_at"
        ),
        {"type": entity_type, "id": entity_id},
    ).mappings()
    return [DocumentOut.model_validate(dict(row)) for row in rows]


def document_record(conn: Connection, document_id: UUID) -> Any:
    row = conn.execute(
        text(
            "select id, entity_type, doc_type, storage_path, sensitivity from public.documents "
            "where id = :id and archived_at is null"
        ),
        {"id": document_id},
    ).first()
    if row is None:
        raise not_found("document")
    return row


def document_url(conn: Connection, storage: Storage, document_id: UUID) -> str:
    row = document_record(conn, document_id)
    url = storage.view_urls(DOCUMENT_BUCKET, [row.storage_path]).get(row.storage_path)
    if url is None:
        raise AppError("UPLOAD_MISSING", "The file is not available", status_code=404)
    return url


def archive_document(conn: Connection, document_id: UUID) -> None:
    document_record(conn, document_id)
    conn.execute(text("update public.documents set archived_at = now() where id = :id"), {"id": document_id})
