"""Reservations (deposits) and sales (SPEC §4.7).

* Deposit received / refunded / forfeited: rules 11, 34, 35.
* Sale draft -> post: rule 12 (cash, bank, mixed legs, deposit applied) and
  rule 26 (trade-in), with cost recognition as a second entry (D-28). The
  sale price posted is the net price after discount (P-12). Business rule 1
  (sold once) is checked here and enforced by a partial unique index.
* Cancellation (owner/accountant, reason required), by the tenant's method
  (D-41): REFUND_LIABILITY (default, P-03) or MIRROR (literal rule 33).
"""

from dataclasses import dataclass, replace
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID, uuid4

from sqlalchemy import Connection, text

from app.core.errors import AppError, not_found
from app.domain.finance import EntryRef, PostingResult, PostingWarning, Preview, PreviewEffect
from app.domain.ledger import ZERO, EntryDraft
from app.domain.money import format_money, ltr, quantize
from app.domain.sales import (
    ReservationIn,
    ReservationOut,
    ReservationSettleIn,
    SaleCancelIn,
    SaleDraftIn,
    SaleListRow,
    SaleOut,
    SalePage,
    SalePaymentOut,
    SaleProfit,
    TradeInIn,
)
from app.domain.vehicles import VehicleIn
from app.integrations.einvoice import adapter_for
from app.services import customers, finance, vehicles
from app.services.posting import engine, rules

_COUNTER = text(
    """
    insert into public.tenant_counters as c (tenant_id, counter_key, last_value)
    values (private.current_tenant_id(), :key, 1)
    on conflict (tenant_id, counter_key) do update set last_value = c.last_value + 1
    returning c.last_value
    """
)


def next_number(conn: Connection, key: str) -> int:
    """Sequential per tenant; taken inside the posting transaction (D-20)."""
    value: int = conn.execute(_COUNTER, {"key": key}).scalar_one()
    return value


def _money(amount: Decimal, info: finance.TenantInfo, language: Literal["ar", "en"]) -> str:
    return format_money(amount, info.currency, language)


# =====================================================================================================
# Reservations and deposits (rules 11, 34, 35)
# =====================================================================================================

_RESERVATIONS = """
    select r.id, r.vehicle_id, v.stock_no, concat_ws(' ', v.make, v.model, v.year) as vehicle_label,
           r.customer_id, c.name as customer_name, r.reservation_date, r.deposit_amount, r.cash_account_id,
           r.expires_on, r.status, r.settled_on, je.entry_no, r.sale_id
      from public.reservations r
      join public.vehicles v on v.id = r.vehicle_id
      join public.customers c on c.id = r.customer_id
      join public.journal_entries je on je.id = r.journal_entry_id
"""


def _reservation_out(row: Any, today: date) -> ReservationOut:
    data = dict(row)
    data["expired"] = data["status"] == "ACTIVE" and data["expires_on"] is not None and data["expires_on"] < today
    return ReservationOut.model_validate(data)


def get_reservation(conn: Connection, reservation_id: UUID) -> ReservationOut:
    row = conn.execute(text(_RESERVATIONS + " where r.id = :id"), {"id": reservation_id}).mappings().first()
    if row is None:
        raise not_found("reservation")
    return _reservation_out(row, finance.tenant_info(conn).today)


def list_reservations(conn: Connection, *, status: str | None, vehicle_id: UUID | None) -> list[ReservationOut]:
    today = finance.tenant_info(conn).today
    rows = conn.execute(
        text(
            _RESERVATIONS
            + """
             where (cast(:status as text) is null or r.status = :status)
               and (cast(:vehicle_id as uuid) is null or r.vehicle_id = :vehicle_id)
             order by r.reservation_date desc, je.entry_no desc
            """
        ),
        {"status": status, "vehicle_id": vehicle_id},
    ).mappings()
    return [_reservation_out(row, today) for row in rows]


@dataclass(frozen=True)
class _ReservationPlan:
    draft: EntryDraft
    vehicle: vehicles.VehicleRef
    customer_name: str
    cash: finance.ActiveCashAccount


def _plan_reservation(
    conn: Connection, info: finance.TenantInfo, payload: ReservationIn, *, lock: bool
) -> _ReservationPlan:
    finance.check_entry_date(info, payload.reservation_date)
    if payload.expires_on is not None and payload.expires_on < payload.reservation_date:
        raise AppError("DATE_RANGE_INVALID", "The reservation cannot expire before it starts", status_code=422)
    vehicle = vehicles.vehicle_ref(conn, payload.vehicle_id, lock=lock)
    if vehicle.status != "AVAILABLE":
        raise AppError(
            "VEHICLE_NOT_AVAILABLE",
            "Only an available car can be reserved",
            status_code=409,
            details={"status": vehicle.status},
        )
    customer = customers.active_customer(conn, payload.customer_id)
    cash = finance.active_cash_account(conn, payload.cash_account_id)
    draft = rules.deposit_received(
        entry_date=payload.reservation_date,
        customer_id=customer.id,
        vehicle_id=vehicle.id,
        amount=payload.deposit_amount,
        received_in=cash.ref,
        description=payload.notes or f"عربون {vehicle.label} ({vehicle.stock_no}) من {customer.name}",
        source_id=None,
    )
    return _ReservationPlan(draft=draft, vehicle=vehicle, customer_name=customer.name, cash=cash)


def preview_reservation(conn: Connection, payload: ReservationIn, *, with_lines: bool) -> Preview:
    info = finance.tenant_info(conn)
    plan = _plan_reservation(conn, info, payload, lock=False)
    finance.ensure_period_open(conn, payload.reservation_date)
    until_ar = f" حتى {ltr(payload.expires_on.isoformat())}" if payload.expires_on else ""
    until_en = f" until {payload.expires_on.isoformat()}" if payload.expires_on else ""
    return Preview(
        summary_ar=(
            f"سيتم استلام عربون {_money(payload.deposit_amount, info, 'ar')} من {plan.customer_name} "
            f"في «{plan.cash.name_ar}» وحجز {plan.vehicle.label} ({plan.vehicle.stock_no}){until_ar}. "
            "العربون يبقى أمانة للعميل حتى البيع أو الرد."
        ),
        summary_en=(
            f"A deposit of {_money(payload.deposit_amount, info, 'en')} from {plan.customer_name} "
            "will be received into "
            f"“{plan.cash.name_en}” and {plan.vehicle.label} ({plan.vehicle.stock_no}) reserved{until_en}. The deposit "
            "is held for the customer until the sale or a refund."
        ),
        effects=[
            PreviewEffect(
                direction="IN", label_ar=plan.cash.name_ar, label_en=plan.cash.name_en, amount=payload.deposit_amount
            )
        ],
        lines=finance.preview_lines(conn, plan.draft) if with_lines else None,
    )


def create_reservation(conn: Connection, payload: ReservationIn) -> PostingResult[ReservationOut]:
    info = finance.tenant_info(conn)
    plan = _plan_reservation(conn, info, payload, lock=True)
    reservation_id = uuid4()
    posted = engine.post(conn, replace(plan.draft, source_id=reservation_id))
    with vehicles.vehicle_errors():
        conn.execute(
            text(
                """
                insert into public.reservations
                  (id, tenant_id, vehicle_id, customer_id, reservation_date, deposit_amount, cash_account_id,
                   expires_on, notes, journal_entry_id)
                values (:id, private.current_tenant_id(), :vehicle_id, :customer_id, :reservation_date, :deposit_amount,
                        :cash_account_id, :expires_on, :notes, :entry)
                """
            ),
            {**payload.model_dump(), "id": reservation_id, "entry": posted.id},
        )
    vehicles.set_status(conn, payload.vehicle_id, "RESERVED", f"حجز بعربون من {plan.customer_name}")
    return PostingResult[ReservationOut](
        document=get_reservation(conn, reservation_id),
        journal_entries=[EntryRef(id=posted.id, entry_no=posted.entry_no)],
    )


def _plan_settle(
    conn: Connection, info: finance.TenantInfo, reservation: ReservationOut, payload: ReservationSettleIn
) -> tuple[EntryDraft, finance.ActiveCashAccount | None]:
    finance.check_entry_date(info, payload.settle_date)
    if reservation.status not in ("ACTIVE", "RELEASED"):
        raise AppError(
            "RESERVATION_NOT_ACTIVE",
            "This deposit has already been used, refunded or forfeited",
            status_code=409,
            details={"status": reservation.status},
        )
    if payload.settle_date < reservation.reservation_date:
        raise AppError("DATE_RANGE_INVALID", "The date is before the reservation", status_code=422)
    if payload.action == "REFUND":
        if payload.cash_account_id is None:
            raise AppError("VALIDATION_ERROR", "Choose the account the refund is paid from", status_code=422)
        cash = finance.active_cash_account(conn, payload.cash_account_id)
        draft = rules.deposit_refunded(
            entry_date=payload.settle_date,
            customer_id=reservation.customer_id,
            vehicle_id=reservation.vehicle_id,
            amount=reservation.deposit_amount,
            paid_from=cash.ref,
            description=(
                f"رد عربون {reservation.vehicle_label} ({reservation.stock_no}) إلى {reservation.customer_name}"
            ),
            source_id=reservation.id,
        )
        return draft, cash
    draft = rules.deposit_forfeited(
        entry_date=payload.settle_date,
        customer_id=reservation.customer_id,
        vehicle_id=reservation.vehicle_id,
        amount=reservation.deposit_amount,
        description=f"مصادرة عربون {reservation.vehicle_label} ({reservation.stock_no}) — {reservation.customer_name}",
        source_id=reservation.id,
    )
    return draft, None


def preview_settle(
    conn: Connection, reservation_id: UUID, payload: ReservationSettleIn, *, with_lines: bool
) -> Preview:
    info = finance.tenant_info(conn)
    reservation = get_reservation(conn, reservation_id)
    draft, cash = _plan_settle(conn, info, reservation, payload)
    finance.ensure_period_open(conn, payload.settle_date)
    warnings = finance.check_cash(conn, info, draft.cash_effects(), lock=False)
    amount_ar, amount_en = (
        _money(reservation.deposit_amount, info, "ar"),
        _money(reservation.deposit_amount, info, "en"),
    )
    release_ar = "، ويُلغى حجز السيارة" if reservation.status == "ACTIVE" else ""
    release_en = "; the car is no longer reserved" if reservation.status == "ACTIVE" else ""
    if cash is not None:
        summary_ar = f"سيتم رد العربون {amount_ar} إلى {reservation.customer_name} من «{cash.name_ar}»{release_ar}."
        summary_en = (
            f"The deposit of {amount_en} will be refunded to {reservation.customer_name} from “{cash.name_en}”"
            f"{release_en}."
        )
        effects = [
            PreviewEffect(
                direction="OUT", label_ar=cash.name_ar, label_en=cash.name_en, amount=reservation.deposit_amount
            )
        ]
    else:
        summary_ar = f"سيتم مصادرة العربون {amount_ar} من {reservation.customer_name} وتسجيله كإيراد آخر{release_ar}."
        summary_en = (
            f"The deposit of {amount_en} from {reservation.customer_name} will be kept and recorded as other income"
            f"{release_en}."
        )
        effects = []
    return Preview(
        summary_ar=summary_ar,
        summary_en=summary_en,
        effects=effects,
        warnings=warnings,
        lines=finance.preview_lines(conn, draft) if with_lines else None,
    )


def settle_reservation(
    conn: Connection, reservation_id: UUID, payload: ReservationSettleIn
) -> PostingResult[ReservationOut]:
    info = finance.tenant_info(conn)
    conn.execute(text("select 1 from public.reservations where id = :id for update"), {"id": reservation_id})
    reservation = get_reservation(conn, reservation_id)
    draft, _ = _plan_settle(conn, info, reservation, payload)
    warnings = finance.check_cash(conn, info, draft.cash_effects(), lock=True)
    posted = engine.post(conn, draft)
    conn.execute(
        text(
            """
            update public.reservations
               set status = :status, settled_on = :settled_on, settle_cash_account_id = :cash, settle_entry_id = :entry
             where id = :id
            """
        ),
        {
            "status": "REFUNDED" if payload.action == "REFUND" else "FORFEITED",
            "settled_on": payload.settle_date,
            "cash": payload.cash_account_id if payload.action == "REFUND" else None,
            "entry": posted.id,
            "id": reservation_id,
        },
    )
    if reservation.status == "ACTIVE":
        vehicle = vehicles.vehicle_ref(conn, reservation.vehicle_id, lock=True)
        if vehicle.status == "RESERVED":
            reason = "رد العربون" if payload.action == "REFUND" else "مصادرة العربون"
            vehicles.set_status(conn, reservation.vehicle_id, "AVAILABLE", reason)
    return PostingResult[ReservationOut](
        document=get_reservation(conn, reservation_id),
        journal_entries=[EntryRef(id=posted.id, entry_no=posted.entry_no)],
        warnings=warnings,
    )


# =====================================================================================================
# Sales
# =====================================================================================================

_SALES = """
    select s.*, v.stock_no, concat_ws(' ', v.make, v.model, v.year) as vehicle_label,
           c.name as buyer_name, c.phone_primary as buyer_phone, je.entry_no, cje.entry_no as cost_entry_no
      from public.sales s
      join public.vehicles v on v.id = s.vehicle_id
      join public.customers c on c.id = s.buyer_customer_id
      left join public.journal_entries je on je.id = s.journal_entry_id
      left join public.journal_entries cje on cje.id = s.cost_journal_entry_id
"""

_PAYMENTS = text(
    """
    select p.cash_account_id, ca.name_ar as cash_account_name_ar, ca.name_en as cash_account_name_en,
           p.payment_method_id, p.amount, p.reference
      from public.sale_payments p join public.cash_accounts ca on ca.id = p.cash_account_id
     where p.sale_id = :id
     order by p.line_no, p.id
    """
)


def _sale_row(conn: Connection, sale_id: UUID, *, lock: bool = False) -> Any:
    if lock:
        conn.execute(text("select 1 from public.sales where id = :id for update"), {"id": sale_id})
    row = conn.execute(text(_SALES + " where s.id = :id"), {"id": sale_id}).mappings().first()
    if row is None:
        raise not_found("sale")
    return row


def _visible(row: Any, *, viewer_id: UUID, see_all_drafts: bool) -> None:
    # Sales staff see posted sales and their own drafts (ARCHITECTURE §7).
    if row["status"] == "DRAFT" and not see_all_drafts and row["created_by"] != viewer_id:
        raise not_found("sale")


def _deposit_of(conn: Connection, reservation_id: UUID | None) -> Decimal:
    if reservation_id is None:
        return ZERO
    amount = conn.execute(
        text("select deposit_amount from public.reservations where id = :id"), {"id": reservation_id}
    ).scalar_one_or_none()
    return Decimal(amount) if amount is not None else ZERO


def get_sale(conn: Connection, sale_id: UUID, *, viewer_id: UUID, see_all_drafts: bool, with_profit: bool) -> SaleOut:
    row = _sale_row(conn, sale_id)
    _visible(row, viewer_id=viewer_id, see_all_drafts=see_all_drafts)
    payments = [SalePaymentOut.model_validate(dict(p)) for p in conn.execute(_PAYMENTS, {"id": sale_id}).mappings()]
    paid = sum((p.amount for p in payments), ZERO)
    deposit = Decimal(row["deposit_applied"]) if row["status"] != "DRAFT" else _deposit_of(conn, row["reservation_id"])
    trade_in_value = Decimal(row["trade_in_value"])
    sale = SaleOut(
        id=row["id"],
        sale_no=row["sale_no"],
        status=row["status"],
        vehicle_id=row["vehicle_id"],
        stock_no=row["stock_no"],
        vehicle_label=row["vehicle_label"],
        buyer_customer_id=row["buyer_customer_id"],
        buyer_name=row["buyer_name"],
        buyer_phone=row["buyer_phone"],
        sale_date=row["sale_date"],
        list_price=row["list_price"],
        discount=row["discount"],
        sale_price=row["sale_price"],
        reservation_id=row["reservation_id"],
        deposit_applied=deposit,
        trade_in=TradeInIn.model_validate(row["trade_in"]) if row["trade_in"] else None,
        trade_in_value=trade_in_value,
        trade_in_vehicle_id=row["trade_in_vehicle_id"],
        payments=payments,
        paid_total=paid,
        remaining=Decimal(row["sale_price"]) - paid - deposit - trade_in_value,
        invoice_no=row["invoice_no"],
        einvoice_status=row["einvoice_status"],
        entry_no=row["entry_no"],
        cost_entry_no=row["cost_entry_no"],
        cancellation_method=row["cancellation_method"],
        cancel_date=row["cancel_date"],
        cancel_reason=row["cancel_reason"],
        created_at=row["created_at"],
        created_by_me=row["created_by"] == viewer_id,
        notes=row["notes"],
    )
    if with_profit and row["status"] == "POSTED":
        totals = vehicles.cost_totals(conn, [row["vehicle_id"]])[row["vehicle_id"]]
        gross = Decimal(row["sale_price"]) - totals.cogs
        sale.profit = SaleProfit(
            cost=totals.cogs,
            gross_profit=gross,
            profit_pct=quantize(gross * 100 / Decimal(row["sale_price"])),
        )
    return sale


def list_sales(
    conn: Connection,
    *,
    status: str | None,
    q: str | None,
    date_from: date | None,
    date_to: date | None,
    viewer_id: UUID,
    see_all_drafts: bool,
    page: int,
    page_size: int,
) -> SalePage:
    where = """
     where (cast(:status as text) is null or s.status = :status)
       and (cast(:date_from as date) is null or s.sale_date >= :date_from)
       and (cast(:date_to as date) is null or s.sale_date <= :date_to)
       and (s.status <> 'DRAFT' or :all_drafts or s.created_by = :viewer)
       and (cast(:q as text) is null or s.sale_no ilike '%' || :q || '%' or s.invoice_no ilike '%' || :q || '%'
            or v.stock_no ilike '%' || :q || '%' or c.name ilike '%' || :q || '%'
            or concat_ws(' ', v.make, v.model) ilike '%' || :q || '%')
    """
    params = {
        "status": status,
        "date_from": date_from,
        "date_to": date_to,
        "all_drafts": see_all_drafts,
        "viewer": viewer_id,
        "q": q.strip() if q and q.strip() else None,
    }
    joins = (
        " from public.sales s join public.vehicles v on v.id = s.vehicle_id"
        " join public.customers c on c.id = s.buyer_customer_id"
    )
    total = conn.execute(text("select count(*)" + joins + where), params).scalar_one()
    rows = conn.execute(
        text(_SALES + where + " order by s.sale_date desc, s.created_at desc limit :limit offset :offset"),
        {**params, "limit": page_size, "offset": (page - 1) * page_size},
    ).mappings()
    items = [
        SaleListRow(
            id=row["id"],
            sale_no=row["sale_no"],
            status=row["status"],
            vehicle_id=row["vehicle_id"],
            stock_no=row["stock_no"],
            vehicle_label=row["vehicle_label"],
            buyer_name=row["buyer_name"],
            sale_date=row["sale_date"],
            sale_price=row["sale_price"],
            invoice_no=row["invoice_no"],
        )
        for row in rows
    ]
    return SalePage(items=items, page=page, page_size=page_size, total=total)


# --- Drafts -------------------------------------------------------------------------------------------


def _validate_draft(conn: Connection, payload: SaleDraftIn) -> None:
    if payload.discount < 0 or payload.discount >= payload.list_price:
        raise AppError("SALE_DISCOUNT_INVALID", "The discount must be less than the price", status_code=422)
    vehicles.vehicle_ref(conn, payload.vehicle_id)
    customers.active_customer(conn, payload.buyer_customer_id)
    for leg in payload.payments:
        finance.active_cash_account(conn, leg.cash_account_id)
    if payload.reservation_id is not None:
        reservation = get_reservation(conn, payload.reservation_id)
        if reservation.vehicle_id != payload.vehicle_id or reservation.customer_id != payload.buyer_customer_id:
            raise AppError("RESERVATION_MISMATCH", "The deposit belongs to another car or customer", status_code=422)


def _write_payments(conn: Connection, sale_id: UUID, payload: SaleDraftIn) -> None:
    conn.execute(text("delete from public.sale_payments where sale_id = :id"), {"id": sale_id})
    for line_no, leg in enumerate(payload.payments, start=1):
        conn.execute(
            text(
                """
                insert into public.sale_payments
                  (tenant_id, sale_id, line_no, cash_account_id, payment_method_id, amount, reference)
                values (private.current_tenant_id(), :sale_id, :line_no, :cash_account_id, :payment_method_id, :amount,
                        :reference)
                """
            ),
            {**leg.model_dump(), "sale_id": sale_id, "line_no": line_no},
        )


def _draft_values(conn: Connection, payload: SaleDraftIn) -> dict[str, Any]:
    trade_in = payload.trade_in
    return {
        "vehicle_id": payload.vehicle_id,
        "buyer_customer_id": payload.buyer_customer_id,
        "sale_date": payload.sale_date,
        "list_price": payload.list_price,
        "discount": payload.discount,
        "sale_price": payload.list_price - payload.discount,
        "reservation_id": payload.reservation_id,
        "deposit_applied": _deposit_of(conn, payload.reservation_id),
        "trade_in_value": trade_in.agreed_value if trade_in else ZERO,
        "trade_in": trade_in.model_dump_json() if trade_in else None,
        "notes": payload.notes,
    }


def create_draft(
    conn: Connection, payload: SaleDraftIn, *, viewer_id: UUID, see_all_drafts: bool, with_profit: bool
) -> SaleOut:
    _validate_draft(conn, payload)
    year = payload.sale_date.year
    sale_id = conn.execute(
        text(
            """
            insert into public.sales
              (tenant_id, sale_no, vehicle_id, buyer_customer_id, sale_date, list_price, discount, sale_price,
               reservation_id, deposit_applied, trade_in_value, trade_in, notes)
            values (private.current_tenant_id(), :sale_no, :vehicle_id, :buyer_customer_id, :sale_date, :list_price,
                    :discount, :sale_price, :reservation_id, :deposit_applied, :trade_in_value,
                    cast(:trade_in as jsonb), :notes)
            returning id
            """
        ),
        {**_draft_values(conn, payload), "sale_no": f"S-{year}-{next_number(conn, f'sale-{year}'):04d}"},
    ).scalar_one()
    _write_payments(conn, sale_id, payload)
    return get_sale(conn, sale_id, viewer_id=viewer_id, see_all_drafts=see_all_drafts, with_profit=with_profit)


def _editable_draft(conn: Connection, sale_id: UUID, *, viewer_id: UUID, can_edit_others: bool) -> Any:
    row = _sale_row(conn, sale_id, lock=True)
    _visible(row, viewer_id=viewer_id, see_all_drafts=can_edit_others)
    if row["status"] != "DRAFT":
        raise AppError("SALE_NOT_DRAFT", "Only a draft sale can be changed", status_code=409)
    if not can_edit_others and row["created_by"] != viewer_id:
        raise AppError("SALE_NOT_DRAFT", "Only your own drafts can be changed", status_code=409)
    return row


def update_draft(
    conn: Connection, sale_id: UUID, payload: SaleDraftIn, *, viewer_id: UUID, can_edit_others: bool, with_profit: bool
) -> SaleOut:
    _editable_draft(conn, sale_id, viewer_id=viewer_id, can_edit_others=can_edit_others)
    _validate_draft(conn, payload)
    values = _draft_values(conn, payload)
    assignments = ", ".join(f"{column} = :{column}" for column in values if column != "trade_in")
    conn.execute(
        text(f"update public.sales set {assignments}, trade_in = cast(:trade_in as jsonb) where id = :id"),  # noqa: S608 - fixed keys
        {**values, "id": sale_id},
    )
    _write_payments(conn, sale_id, payload)
    return get_sale(conn, sale_id, viewer_id=viewer_id, see_all_drafts=can_edit_others, with_profit=with_profit)


def delete_draft(conn: Connection, sale_id: UUID, *, viewer_id: UUID, can_edit_others: bool) -> None:
    _editable_draft(conn, sale_id, viewer_id=viewer_id, can_edit_others=can_edit_others)
    conn.execute(text("delete from public.sales where id = :id"), {"id": sale_id})


# --- Posting (rules 12, 26; D-28) -------------------------------------------------------------------------


@dataclass(frozen=True)
class _SalePlan:
    sale: Any
    vehicle: vehicles.VehicleRef
    legs: list[tuple[finance.ActiveCashAccount, Decimal]]
    deposit: Decimal
    reservation_id: UUID | None
    trade_in: TradeInIn | None
    cost: Decimal
    sale_draft: EntryDraft
    cost_draft: EntryDraft


def _plan_post(
    conn: Connection, info: finance.TenantInfo, sale_id: UUID, *, lock: bool, trade_in_vehicle_id: UUID
) -> _SalePlan:
    sale = _sale_row(conn, sale_id, lock=lock)
    if sale["status"] != "DRAFT":
        raise AppError("SALE_NOT_DRAFT", "This sale is already posted or cancelled", status_code=409)
    finance.check_entry_date(info, sale["sale_date"])
    vehicle = vehicles.vehicle_ref(conn, sale["vehicle_id"], lock=lock)
    if vehicle.ownership_type != "OWNED":
        raise AppError("VEHICLE_NOT_OWNED", "Consigned cars are sold through consignment (Phase 6)", status_code=422)
    if vehicle.status in ("SOLD", "DELIVERED"):
        raise AppError("VEHICLE_ALREADY_SOLD", "This vehicle has already been sold", status_code=409)

    reservation_id = sale["reservation_id"]
    deposit = ZERO
    if reservation_id is not None:
        reservation = get_reservation(conn, reservation_id)
        if reservation.status not in ("ACTIVE", "RELEASED"):
            raise AppError("RESERVATION_NOT_ACTIVE", "The deposit has already been used or refunded", status_code=409)
        if reservation.vehicle_id != vehicle.id or reservation.customer_id != sale["buyer_customer_id"]:
            raise AppError("RESERVATION_MISMATCH", "The deposit belongs to another car or customer", status_code=422)
        deposit = reservation.deposit_amount
    if vehicle.status == "RESERVED":
        holder = conn.execute(
            text(
                "select r.id, c.name from public.reservations r join public.customers c on c.id = r.customer_id "
                "where r.vehicle_id = :id and r.status = 'ACTIVE'"
            ),
            {"id": vehicle.id},
        ).first()
        if holder is not None and holder.id != reservation_id:
            raise AppError(
                "VEHICLE_RESERVED",
                "The car is reserved for another customer",
                status_code=409,
                details={"customer_name": holder.name},
            )
    elif vehicle.status != "AVAILABLE":
        raise AppError(
            "VEHICLE_NOT_AVAILABLE",
            "Only an available car can be sold",
            status_code=409,
            details={"status": vehicle.status},
        )

    cost = vehicles.inventory_cost(conn, vehicle.id)
    if cost <= 0:
        # Profit uses recorded costs only (business rule 5): record the purchase first.
        raise AppError("VEHICLE_COST_MISSING", "Record the purchase of this car before selling it", status_code=422)

    payments = list(conn.execute(_PAYMENTS, {"id": sale_id}).mappings())
    legs = [(finance.active_cash_account(conn, p["cash_account_id"]), Decimal(p["amount"])) for p in payments]
    trade_in = TradeInIn.model_validate(sale["trade_in"]) if sale["trade_in"] else None
    sale_price = Decimal(sale["sale_price"])
    paid = sum((amount for _, amount in legs), ZERO)
    trade_value = trade_in.agreed_value if trade_in else ZERO
    if paid + deposit + trade_value != sale_price:
        raise AppError(
            "SALE_AMOUNTS_MISMATCH",
            "Payments, deposit and trade-in must add up to the sale price",
            status_code=422,
            details={
                "sale_price": f"{sale_price:.2f}",
                "paid": f"{paid:.2f}",
                "deposit": f"{deposit:.2f}",
                "trade_in": f"{trade_value:.2f}",
                "remaining": f"{sale_price - paid - deposit - trade_value:.2f}",
            },
        )
    description = f"بيع {vehicle.label} ({vehicle.stock_no}) إلى {sale['buyer_name']} — {sale['sale_no']}"
    sale_draft = rules.sale(
        entry_date=sale["sale_date"],
        vehicle_id=vehicle.id,
        buyer_id=sale["buyer_customer_id"],
        sale_price=sale_price,
        payments=[(account.ref, amount) for account, amount in legs],
        deposit_applied=deposit,
        trade_in=(trade_in_vehicle_id, trade_value) if trade_in else None,
        description=description,
        source_id=sale_id,
    )
    cost_draft = rules.cost_of_sale(
        entry_date=sale["sale_date"],
        vehicle_id=vehicle.id,
        cost=cost,
        description=f"تكلفة {vehicle.label} ({vehicle.stock_no}) — {sale['sale_no']}",
        source_id=sale_id,
    )
    return _SalePlan(
        sale=sale,
        vehicle=vehicle,
        legs=legs,
        deposit=deposit,
        reservation_id=reservation_id,
        trade_in=trade_in,
        cost=cost,
        sale_draft=sale_draft,
        cost_draft=cost_draft,
    )


def preview_post(conn: Connection, sale_id: UUID, *, with_lines: bool, with_profit: bool) -> Preview:
    info = finance.tenant_info(conn)
    plan = _plan_post(conn, info, sale_id, lock=False, trade_in_vehicle_id=uuid4())
    finance.ensure_period_open(conn, plan.sale["sale_date"])
    sale_price = Decimal(plan.sale["sale_price"])
    parts_ar = [f"{_money(amount, info, 'ar')} في «{account.name_ar}»" for account, amount in plan.legs]
    parts_en = [f"{_money(amount, info, 'en')} into “{account.name_en}”" for account, amount in plan.legs]
    if plan.deposit > 0:
        parts_ar.append(f"العربون المدفوع {_money(plan.deposit, info, 'ar')}")
        parts_en.append(f"the deposit already paid, {_money(plan.deposit, info, 'en')}")
    if plan.trade_in:
        label = vehicles.vehicle_label(plan.trade_in.make, plan.trade_in.model, plan.trade_in.year)
        parts_ar.append(f"سيارة العميل {label} بقيمة {_money(plan.trade_in.agreed_value, info, 'ar')} تدخل المخزون")
        parts_en.append(
            f"the customer's {label} at {_money(plan.trade_in.agreed_value, info, 'en')}, which enters stock"
        )
    discount = Decimal(plan.sale["discount"])
    discount_ar = f" بعد خصم {_money(discount, info, 'ar')}" if discount > 0 else ""
    discount_en = f" after a discount of {_money(discount, info, 'en')}" if discount > 0 else ""
    summary_ar = (
        f"سيتم بيع {plan.vehicle.label} ({plan.vehicle.stock_no}) إلى {plan.sale['buyer_name']} بسعر "
        f"{_money(sale_price, info, 'ar')}{discount_ar} بتاريخ {ltr(plan.sale['sale_date'].isoformat())}. "
        f"التحصيل: {'، '.join(parts_ar)}. تصبح السيارة مباعة."
    )
    summary_en = (
        f"{plan.vehicle.label} ({plan.vehicle.stock_no}) will be sold to {plan.sale['buyer_name']} for "
        f"{_money(sale_price, info, 'en')}{discount_en} on {plan.sale['sale_date'].isoformat()}. "
        f"Paid by: {'; '.join(parts_en)}. The car becomes sold."
    )
    if with_profit:
        profit = sale_price - plan.cost
        summary_ar += f" التكلفة {_money(plan.cost, info, 'ar')} والربح {_money(profit, info, 'ar')}."
        summary_en += f" Cost {_money(plan.cost, info, 'en')}, profit {_money(profit, info, 'en')}."
    lines = None
    if with_lines:
        lines = finance.preview_lines(conn, plan.sale_draft) + finance.preview_lines(conn, plan.cost_draft)
    return Preview(
        summary_ar=summary_ar,
        summary_en=summary_en,
        effects=[
            PreviewEffect(direction="IN", label_ar=account.name_ar, label_en=account.name_en, amount=amount)
            for account, amount in plan.legs
        ],
        warnings=_profit_warnings(sale_price, plan.cost, with_profit),
        lines=lines,
    )


def _profit_warnings(sale_price: Decimal, cost: Decimal, with_profit: bool) -> list[PostingWarning]:
    if with_profit and sale_price < cost:
        return [PostingWarning(code="SALE_BELOW_COST", details={"loss": f"{cost - sale_price:.2f}"})]
    return []


def _create_trade_in_vehicle(conn: Connection, trade_in: TradeInIn, sale_date: date, buyer_name: str) -> UUID:
    vehicle_id = vehicles.create_vehicle(
        conn,
        VehicleIn(
            make=trade_in.make,
            model=trade_in.model,
            year=trade_in.year,
            vin=trade_in.vin,
            plate_no=trade_in.plate_no,
            color_ext=trade_in.color_ext,
            mileage_km=trade_in.mileage_km,
            transmission=trade_in.transmission,
            fuel=trade_in.fuel,
        ),
        acquisition_source="TRADE_IN",
        reason=f"استبدال من {buyer_name}",
    )
    # Its own cost file starts at the agreed value; days in stock start at the sale (Q-24).
    conn.execute(text("update public.vehicles set stock_date = :d where id = :id"), {"d": sale_date, "id": vehicle_id})
    return vehicle_id


def post_sale(conn: Connection, sale_id: UUID, *, user_id: UUID, with_profit: bool) -> PostingResult[SaleOut]:
    info = finance.tenant_info(conn)
    trade_in_vehicle_id = uuid4()
    plan = _plan_post(conn, info, sale_id, lock=True, trade_in_vehicle_id=trade_in_vehicle_id)
    warnings = finance.check_cash(conn, info, plan.sale_draft.cash_effects(), lock=True)
    warnings += _profit_warnings(Decimal(plan.sale["sale_price"]), plan.cost, with_profit)

    created_trade_in: UUID | None = None
    sale_draft = plan.sale_draft
    if plan.trade_in is not None:
        created_trade_in = _create_trade_in_vehicle(
            conn, plan.trade_in, plan.sale["sale_date"], plan.sale["buyer_name"]
        )
        sale_draft = replace(
            sale_draft,
            lines=tuple(
                replace(line, vehicle_id=created_trade_in) if line.vehicle_id == trade_in_vehicle_id else line
                for line in sale_draft.lines
            ),
        )

    sale_entry = engine.post(conn, sale_draft)
    cost_entry = engine.post(conn, plan.cost_draft)
    year = plan.sale["sale_date"].year
    pack = conn.execute(
        text(
            "select cp.invoice_prefix, cp.einvoice_adapter from public.tenants t "
            "join public.country_packs cp on cp.code = t.country_code where t.id = private.current_tenant_id()"
        )
    ).one()
    # Invoice numbers are taken only when posting, so drafts leave no gaps (G-29).
    invoice_no = f"{pack.invoice_prefix}-{year}-{next_number(conn, f'invoice-{year}'):05d}"
    einvoice = adapter_for(pack.einvoice_adapter).submit_document(invoice_no)
    with vehicles.vehicle_errors():
        conn.execute(
            text(
                """
                update public.sales
                   set status = 'POSTED', posted_at = now(), posted_by = :user, journal_entry_id = :entry,
                       cost_journal_entry_id = :cost_entry, invoice_no = :invoice_no, deposit_applied = :deposit,
                       trade_in_vehicle_id = :trade_in_vehicle, einvoice_status = :einvoice_status,
                       einvoice_uuid = :einvoice_uuid
                 where id = :id
                """
            ),
            {
                "user": user_id,
                "entry": sale_entry.id,
                "cost_entry": cost_entry.id,
                "invoice_no": invoice_no,
                "deposit": plan.deposit,
                "trade_in_vehicle": created_trade_in,
                "einvoice_status": einvoice.status,
                "einvoice_uuid": einvoice.document_uuid,
                "id": sale_id,
            },
        )
    vehicles.set_status(conn, plan.vehicle.id, "SOLD", f"بيع {plan.sale['sale_no']}")
    if plan.reservation_id is not None:
        conn.execute(
            text("update public.reservations set status = 'APPLIED', sale_id = :sale where id = :id"),
            {"sale": sale_id, "id": plan.reservation_id},
        )
    customers.flag(conn, plan.sale["buyer_customer_id"], buyer=True, seller=plan.trade_in is not None)
    if plan.trade_in is not None and created_trade_in is not None:
        conn.execute(
            text(
                """
                insert into public.vehicle_purchases
                  (tenant_id, vehicle_id, seller_customer_id, source, purchase_date, price, journal_entry_id, notes)
                values (private.current_tenant_id(), :vehicle, :seller, 'TRADE_IN', :d, :price, :entry, :notes)
                """
            ),
            {
                "vehicle": created_trade_in,
                "seller": plan.sale["buyer_customer_id"],
                "d": plan.sale["sale_date"],
                "price": plan.trade_in.agreed_value,
                "entry": sale_entry.id,
                "notes": f"استبدال في {plan.sale['sale_no']}",
            },
        )
        vehicles.set_status(conn, created_trade_in, "IN_PREPARATION", f"استبدال في {plan.sale['sale_no']}")
    return PostingResult[SaleOut](
        document=get_sale(conn, sale_id, viewer_id=user_id, see_all_drafts=True, with_profit=with_profit),
        journal_entries=[
            EntryRef(id=sale_entry.id, entry_no=sale_entry.entry_no),
            EntryRef(id=cost_entry.id, entry_no=cost_entry.entry_no),
        ],
        warnings=warnings,
    )


# --- Cancellation (rule 33 / P-03, D-41) -------------------------------------------------------------------------


@dataclass(frozen=True)
class _CancelPlan:
    sale: Any
    method: str
    cancel_date: date
    paid: Decimal
    legs: list[tuple[str, str, Decimal]]
    credit_draft: EntryDraft | None
    mirror_cash: dict[UUID, Decimal]


def _plan_cancel(
    conn: Connection, info: finance.TenantInfo, sale_id: UUID, payload: SaleCancelIn, *, lock: bool
) -> _CancelPlan:
    sale = _sale_row(conn, sale_id, lock=lock)
    if sale["status"] != "POSTED":
        raise AppError("SALE_NOT_POSTED", "Only a posted sale can be cancelled", status_code=409)
    cancel_date = payload.cancel_date or info.today
    finance.check_entry_date(info, cancel_date)
    if cancel_date < sale["sale_date"]:
        raise AppError("DATE_RANGE_INVALID", "The cancellation cannot be dated before the sale", status_code=422)
    vehicle = vehicles.vehicle_ref(conn, sale["vehicle_id"], lock=lock)
    if vehicle.status != "SOLD":
        # Q-30 default: a delivered car's sale is not cancelled.
        raise AppError("SALE_DELIVERED", "The car has been delivered; the sale cannot be cancelled", status_code=409)
    if sale["trade_in_vehicle_id"] is not None:
        _check_trade_in_returnable(conn, sale["trade_in_vehicle_id"])

    method = conn.execute(text("select sale_cancellation_method from public.tenant_settings")).scalar_one()
    payments = list(conn.execute(_PAYMENTS, {"id": sale_id}).mappings())
    paid = sum((Decimal(p["amount"]) for p in payments), ZERO) + Decimal(sale["deposit_applied"])
    legs = [
        (p["cash_account_name_ar"], p["cash_account_name_en"] or p["cash_account_name_ar"], Decimal(p["amount"]))
        for p in payments
    ]
    credit_draft = None
    mirror_cash: dict[UUID, Decimal] = {}
    if method == "REFUND_LIABILITY":
        trade_value = Decimal(sale["trade_in_value"])
        credit_draft = rules.sale_cancellation_to_credit(
            entry_date=cancel_date,
            vehicle_id=vehicle.id,
            buyer_id=sale["buyer_customer_id"],
            sale_price=Decimal(sale["sale_price"]),
            amount_paid=paid,
            trade_in=(sale["trade_in_vehicle_id"], trade_value) if trade_value > 0 else None,
            description=f"إلغاء بيع {vehicle.label} ({vehicle.stock_no}) — {sale['sale_no']}: {payload.reason}",
            source_id=sale_id,
        )
    else:
        mirror = rules.reversal_lines(engine.entry_lines(conn, sale["journal_entry_id"]))
        for line in mirror:
            if line.cash_account_id is not None:
                mirror_cash[line.cash_account_id] = (
                    mirror_cash.get(line.cash_account_id, ZERO) + line.debit - line.credit
                )
    return _CancelPlan(
        sale=sale,
        method=method,
        cancel_date=cancel_date,
        paid=paid,
        legs=legs,
        credit_draft=credit_draft,
        mirror_cash=mirror_cash,
    )


def _check_trade_in_returnable(conn: Connection, trade_in_vehicle_id: UUID) -> None:
    """The customer's car goes back to them only if nothing has happened to it yet (G-23, Q-30)."""
    row = conn.execute(
        text(
            """
            select v.status,
                   (select count(*) from public.vehicle_expenses x where x.vehicle_id = v.id and x.status = 'POSTED')
                     as expenses
              from public.vehicles v where v.id = :id
            """
        ),
        {"id": trade_in_vehicle_id},
    ).one()
    if row.status not in ("DRAFT", "IN_PREPARATION", "AVAILABLE") or row.expenses:
        raise AppError(
            "SALE_TRADE_IN_USED",
            "The trade-in car has been sold, reserved or had expenses; the sale cannot be cancelled",
            status_code=409,
        )


def preview_cancel(conn: Connection, sale_id: UUID, payload: SaleCancelIn, *, with_lines: bool) -> Preview:
    info = finance.tenant_info(conn)
    plan = _plan_cancel(conn, info, sale_id, payload, lock=False)
    finance.ensure_period_open(conn, plan.cancel_date)
    sale = plan.sale
    head_ar = (
        f"سيتم إلغاء بيع {sale['vehicle_label']} ({sale['stock_no']}) إلى {sale['buyer_name']} "
        f"بتاريخ {ltr(plan.cancel_date.isoformat())} وإرجاع السيارة للمخزون."
    )
    head_en = (
        f"The sale of {sale['vehicle_label']} ({sale['stock_no']}) to {sale['buyer_name']} will be cancelled on "
        f"{plan.cancel_date.isoformat()} and the car returned to stock."
    )
    trade_ar = " سيارة الاستبدال تُعاد للعميل." if sale["trade_in_vehicle_id"] else ""
    trade_en = " The trade-in car goes back to the customer." if sale["trade_in_vehicle_id"] else ""
    effects: list[PreviewEffect] = []
    warnings: list[PostingWarning] = []
    if plan.method == "REFUND_LIABILITY":
        body_ar = (
            f" المبلغ الذي دفعه العميل ({_money(plan.paid, info, 'ar')}) يصبح مستحقاً له، ويُصرف لاحقاً من صفحة العميل؛ "
            "لن يخرج أي مبلغ من الخزنة الآن."
        )
        body_en = (
            f" What the customer paid ({_money(plan.paid, info, 'en')}) becomes owed to them "
            "and is refunded later from "
            "the customer page; no money leaves the cash box now."
        )
        lines = finance.preview_lines(conn, plan.credit_draft) if with_lines and plan.credit_draft else None
    else:
        body_ar = " يُعكس قيد البيع كما هو: " + "، ".join(
            f"خصم {_money(amount, info, 'ar')} من «{name_ar}»" for name_ar, _, amount in plan.legs
        )
        body_en = " The sale entry is reversed as it was: " + "; ".join(
            f"{_money(amount, info, 'en')} out of “{name_en}”" for _, name_en, amount in plan.legs
        )
        if Decimal(sale["deposit_applied"]) > 0:
            body_ar += "، ويعود العربون أمانة للعميل حتى يُرد أو يُصادر"
            body_en += "; the deposit is held for the customer again until refunded or forfeited"
        body_ar += "."
        body_en += "."
        effects = [
            PreviewEffect(direction="OUT", label_ar=name_ar, label_en=name_en, amount=amount)
            for name_ar, name_en, amount in plan.legs
        ]
        warnings = finance.check_cash(conn, info, plan.mirror_cash, lock=False)
        lines = None
    return Preview(
        summary_ar=head_ar + body_ar + trade_ar + f" السبب: {payload.reason}",
        summary_en=head_en + body_en + trade_en + f" Reason: {payload.reason}",
        effects=effects,
        warnings=warnings,
        lines=lines,
    )


def cancel_sale(
    conn: Connection, sale_id: UUID, payload: SaleCancelIn, *, user_id: UUID, with_profit: bool
) -> PostingResult[SaleOut]:
    info = finance.tenant_info(conn)
    plan = _plan_cancel(conn, info, sale_id, payload, lock=True)
    sale = plan.sale
    reason = payload.reason
    warnings: list[PostingWarning] = []
    if plan.method == "REFUND_LIABILITY" and plan.credit_draft is not None:
        cancel_entry = engine.post(conn, plan.credit_draft)
    else:
        warnings = finance.check_cash(conn, info, plan.mirror_cash, lock=True)
        cancel_entry = engine.reverse(conn, sale["journal_entry_id"], reason, plan.cancel_date)
    cost_entry = engine.reverse(conn, sale["cost_journal_entry_id"], reason, plan.cancel_date)
    conn.execute(
        text(
            """
            update public.sales
               set status = 'CANCELLED', cancellation_method = :method, cancel_date = :cancel_date,
                   cancel_reason = :reason, cancelled_at = :now, cancelled_by = :user,
                   cancel_journal_entry_id = :entry, cancel_cost_journal_entry_id = :cost_entry
             where id = :id
            """
        ),
        {
            "method": plan.method,
            "cancel_date": plan.cancel_date,
            "reason": reason,
            "now": datetime.now().astimezone(),
            "user": user_id,
            "entry": cancel_entry.id,
            "cost_entry": cost_entry.id,
            "id": sale_id,
        },
    )
    vehicles.set_status(conn, sale["vehicle_id"], "AVAILABLE", f"إلغاء البيع {sale['sale_no']}: {reason}")
    if sale["trade_in_vehicle_id"] is not None:
        conn.execute(
            text(
                "update public.vehicle_purchases set status = 'REVERSED', reversal_entry_id = :entry "
                "where vehicle_id = :vehicle and source = 'TRADE_IN' and status = 'POSTED'"
            ),
            {"entry": cancel_entry.id, "vehicle": sale["trade_in_vehicle_id"]},
        )
        vehicles.set_status(conn, sale["trade_in_vehicle_id"], "ARCHIVED", f"أُعيدت للعميل بإلغاء {sale['sale_no']}")
    if sale["reservation_id"] is not None and plan.method == "MIRROR":
        # The mirror puts the deposit back on hold; it is refunded or forfeited separately (D-72).
        conn.execute(
            text("update public.reservations set status = 'RELEASED' where id = :id"), {"id": sale["reservation_id"]}
        )
    return PostingResult[SaleOut](
        document=get_sale(conn, sale_id, viewer_id=user_id, see_all_drafts=True, with_profit=with_profit),
        journal_entries=[
            EntryRef(id=cancel_entry.id, entry_no=cancel_entry.entry_no),
            EntryRef(id=cost_entry.id, entry_no=cost_entry.entry_no),
        ],
        warnings=warnings,
    )


def document_context(conn: Connection, sale_id: UUID) -> dict[str, Any]:
    """Everything a printed contract or invoice shows (no cost, no profit)."""
    sale = _sale_row(conn, sale_id)
    if sale["status"] != "POSTED":
        raise AppError("SALE_NOT_POSTED", "Documents are printed for posted sales", status_code=409)
    tenant = (
        conn.execute(
            text(
                """
            select t.name_ar, coalesce(t.name_en, t.name_ar) as name_en, t.address, t.phones, t.commercial_reg_no,
                   t.tax_reg_no, t.country_code, t.currency_code, t.logo_path
              from public.tenants t where t.id = private.current_tenant_id()
            """
            )
        )
        .mappings()
        .one()
    )
    vehicle = (
        conn.execute(
            text(
                "select stock_no, make, model, trim, year, vin, plate_no, color_ext, mileage_km "
                "from public.vehicles where id = :id"
            ),
            {"id": sale["vehicle_id"]},
        )
        .mappings()
        .one()
    )
    payments = [dict(p) for p in conn.execute(_PAYMENTS, {"id": sale_id}).mappings()]
    return {
        "sale": dict(sale),
        "tenant": dict(tenant),
        "vehicle": dict(vehicle),
        "payments": payments,
        "trade_in": TradeInIn.model_validate(sale["trade_in"]) if sale["trade_in"] else None,
    }
