"""Consignment in and out (SPEC §4.4, §4.5) and external showrooms.

* IN: a car received from its owner (a customer, A-06) under an agreement:
  net price, fixed or percentage commission; expenses borne by the owner,
  the showroom or shared. Expenses post rule 10 / P-05 (vehicles service); the
  sale posts rule 16 (sales service); settlements post rule 17 (payout) and
  P-06 (the owner repays expenses). A car goes back to its owner unsold by
  a return (RETURNED_TO_OWNER).
* OUT: an owned car sent to another showroom (never a consigned one, Q-33),
  returned, or sold there (rule 18, three entries); money is collected from
  that showroom (rule 19).

Balances are always read from the ledger (D-26): payable to the owner (2200),
recoverable from the owner (1430), receivable from a showroom (1420).
"""

from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID, uuid4

from sqlalchemy import Connection, text

from app.core.errors import AppError, not_found
from app.core.phone import normalize_phone
from app.domain.consignment import (
    CommissionError,
    ConsignmentIn,
    ConsignmentOut,
    ConsignmentOutOut,
    ConsignmentReturnIn,
    ConsignmentUpdate,
    ConsignorSettlementIn,
    ConsignorSettlementOut,
    ConsignorStatement,
    ConsignOutIn,
    ConsignOutReturnIn,
    ExternalCollectionIn,
    ExternalCollectionOut,
    ExternalSaleIn,
    ExternalShowroomIn,
    ExternalShowroomOut,
    ExternalShowroomStatement,
    ExternalShowroomUpdate,
    StatementLine,
    external_commission_for,
)
from app.domain.finance import EntryRef, PostingResult, Preview, PreviewEffect
from app.domain.ledger import ZERO, EntryDraft
from app.domain.money import format_money, ltr
from app.services import customers, distribution, finance, vehicles
from app.services.posting import engine, rules


def _money(amount: Decimal, info: finance.TenantInfo, language: Literal["ar", "en"]) -> str:
    return format_money(amount, info.currency, language)


def _feature_on(conn: Connection) -> None:
    enabled = conn.execute(
        text("select private.feature_enabled(private.current_tenant_id(), 'consignment')")
    ).scalar_one()
    if not enabled:
        raise AppError("FEATURE_DISABLED", "Consignment is not enabled for this showroom", status_code=403)


# =====================================================================================================
# Ledger balances
# =====================================================================================================

_BALANCE = text(
    """
    select coalesce(sum(l.debit - l.credit), 0)
      from public.journal_lines l join public.ledger_accounts a on a.id = l.ledger_account_id
     where a.system_key = :key
       and (cast(:consignor as uuid) is null or l.consignor_id = :consignor)
       and (cast(:showroom as uuid) is null or l.external_showroom_id = :showroom)
       and (cast(:vehicle as uuid) is null or l.vehicle_id = :vehicle)
    """
)


def _balance(
    conn: Connection,
    key: str,
    *,
    consignor_id: UUID | None = None,
    showroom_id: UUID | None = None,
    vehicle_id: UUID | None = None,
) -> Decimal:
    value = conn.execute(
        _BALANCE, {"key": key, "consignor": consignor_id, "showroom": showroom_id, "vehicle": vehicle_id}
    ).scalar_one()
    return Decimal(value)


def recoverable_balance(conn: Connection, consignor_id: UUID, vehicle_id: UUID) -> Decimal:
    """What the owner still owes back for expenses on this car (1430, debit balance)."""
    return _balance(conn, "CONSIGNOR_RECOVERABLE", consignor_id=consignor_id, vehicle_id=vehicle_id)


def payable_balance(conn: Connection, consignor_id: UUID, vehicle_id: UUID) -> Decimal:
    """What the showroom still owes the owner for this car (2200, credit balance)."""
    return -_balance(conn, "CONSIGNOR_PAYABLE", consignor_id=consignor_id, vehicle_id=vehicle_id)


def showroom_receivable(conn: Connection, showroom_id: UUID) -> Decimal:
    return _balance(conn, "EXTERNAL_SHOWROOM_RECEIVABLE", showroom_id=showroom_id)


def payouts_total(conn: Connection, consignment_id: UUID) -> Decimal:
    value = conn.execute(
        text(
            "select coalesce(sum(amount), 0) from public.consignor_settlements "
            "where consignment_id = :id and kind = 'PAYOUT' and status = 'POSTED'"
        ),
        {"id": consignment_id},
    ).scalar_one()
    return Decimal(value)


# =====================================================================================================
# External showrooms
# =====================================================================================================

_SHOWROOMS = """
    select x.id, x.name, x.contact_name, x.phone, x.address, x.notes, x.archived_at is not null as archived,
           (select count(*) from public.consignments_out o where o.external_showroom_id = x.id and o.status = 'OUT')
             as cars_out
      from public.external_showrooms x
"""


def _showroom_out(conn: Connection, row: Any, with_balance: bool) -> ExternalShowroomOut:
    out = ExternalShowroomOut.model_validate(dict(row))
    if with_balance:
        out.receivable = showroom_receivable(conn, out.id)
    return out


def list_showrooms(conn: Connection, *, include_archived: bool, with_balance: bool) -> list[ExternalShowroomOut]:
    rows = conn.execute(
        text(_SHOWROOMS + " where (:all or x.archived_at is null) order by x.name"), {"all": include_archived}
    ).mappings()
    return [_showroom_out(conn, row, with_balance) for row in rows]


def get_showroom(conn: Connection, showroom_id: UUID, *, with_balance: bool) -> ExternalShowroomOut:
    row = conn.execute(text(_SHOWROOMS + " where x.id = :id"), {"id": showroom_id}).mappings().first()
    if row is None:
        raise not_found("external showroom")
    return _showroom_out(conn, row, with_balance)


def _phone(conn: Connection, phone: str | None) -> str | None:
    if phone is None:
        return None
    return normalize_phone(phone, customers.country_code(conn))


def create_showroom(conn: Connection, payload: ExternalShowroomIn) -> ExternalShowroomOut:
    _feature_on(conn)
    values = payload.model_dump()
    values["phone"] = _phone(conn, payload.phone)
    showroom_id = conn.execute(
        text(
            """
            insert into public.external_showrooms (tenant_id, name, contact_name, phone, address, notes)
            values (private.current_tenant_id(), :name, :contact_name, :phone, :address, :notes)
            returning id
            """
        ),
        values,
    ).scalar_one()
    # Its yard appears in the location history of every car sent there (D-92).
    conn.execute(
        text(
            """
            insert into public.locations (tenant_id, type, name_ar, name_en, external_showroom_id)
            values (private.current_tenant_id(), 'EXTERNAL_SHOWROOM', :name, :name, :id)
            """
        ),
        {"name": payload.name, "id": showroom_id},
    )
    return get_showroom(conn, showroom_id, with_balance=False)


def update_showroom(
    conn: Connection, showroom_id: UUID, changes: ExternalShowroomUpdate, *, with_balance: bool
) -> ExternalShowroomOut:
    current = get_showroom(conn, showroom_id, with_balance=False)
    values = changes.model_dump(exclude_unset=True)
    archived = values.pop("archived", None)
    if "name" in values and not values["name"]:
        raise AppError("VALIDATION_ERROR", "name is required", status_code=422)
    if "phone" in values:
        values["phone"] = _phone(conn, values["phone"])
    if archived and (current.cars_out or showroom_receivable(conn, showroom_id) != 0):
        raise AppError("SHOWROOM_IN_USE", "The showroom still has our cars or owes us money", status_code=409)
    if values:
        assignments = ", ".join(f"{column} = :{column}" for column in values)  # keys from a StrictModel
        conn.execute(
            text(f"update public.external_showrooms set {assignments} where id = :id"),  # noqa: S608
            {**values, "id": showroom_id},
        )
    if "name" in values:
        conn.execute(
            text("update public.locations set name_ar = :name, name_en = :name where external_showroom_id = :id"),
            {"name": values["name"], "id": showroom_id},
        )
    if archived is not None:
        stamp = "now()" if archived else "null"
        conn.execute(
            text(f"update public.external_showrooms set archived_at = {stamp} where id = :id"),  # noqa: S608
            {"id": showroom_id},
        )
        conn.execute(
            text(f"update public.locations set archived_at = {stamp} where external_showroom_id = :id"),  # noqa: S608
            {"id": showroom_id},
        )
    return get_showroom(conn, showroom_id, with_balance=with_balance)


def _active_showroom(conn: Connection, showroom_id: UUID) -> ExternalShowroomOut:
    showroom = get_showroom(conn, showroom_id, with_balance=False)
    if showroom.archived:
        raise AppError("SHOWROOM_INVALID", "Unknown or archived showroom", status_code=422)
    return showroom


# =====================================================================================================
# Consignment IN
# =====================================================================================================

_CONSIGNMENTS = """
    select ci.*, v.stock_no, concat_ws(' ', v.make, v.model, v.year) as vehicle_label, v.status as vehicle_status,
           v.asking_price, c.name as consignor_name, c.phone_primary as consignor_phone,
           s.id as sale_id, s.sale_no, s.sale_price, s.sale_date
      from public.consignments_in ci
      join public.vehicles v on v.id = ci.vehicle_id
      join public.customers c on c.id = ci.consignor_id
      left join public.sales s on s.vehicle_id = ci.vehicle_id and s.status = 'POSTED'
"""


def _settlements(conn: Connection, consignment_id: UUID) -> list[ConsignorSettlementOut]:
    rows = conn.execute(
        text(
            """
            select st.id, st.kind, st.settle_date, st.amount, ca.name_ar as cash_account_name_ar, st.status,
                   je.entry_no, st.notes
              from public.consignor_settlements st
              join public.cash_accounts ca on ca.id = st.cash_account_id
              join public.journal_entries je on je.id = st.journal_entry_id
             where st.consignment_id = :id
             order by st.settle_date, je.entry_no
            """
        ),
        {"id": consignment_id},
    ).mappings()
    return [ConsignorSettlementOut.model_validate(dict(row)) for row in rows]


def _consignment_out(conn: Connection, row: Any, today: date, with_money: bool) -> ConsignmentOut:
    end = row["returned_date"] or row["sale_date"] or today
    out = ConsignmentOut(
        id=row["id"],
        vehicle_id=row["vehicle_id"],
        stock_no=row["stock_no"],
        vehicle_label=row["vehicle_label"],
        vehicle_status=row["vehicle_status"],
        consignor_id=row["consignor_id"],
        consignor_name=row["consignor_name"],
        consignor_phone=row["consignor_phone"],
        agreement_date=row["agreement_date"],
        end_date=row["end_date"],
        expired=row["status"] == "ACTIVE" and row["end_date"] is not None and row["end_date"] < today,
        terms_type=row["terms_type"],
        net_price_to_owner=row["net_price_to_owner"],
        commission_value=row["commission_value"],
        expenses_borne_by=row["expenses_borne_by"],
        shared_owner_pct=row["shared_owner_pct"],
        asking_price=row["asking_price"],
        status=row["status"],
        returned_date=row["returned_date"],
        days_with_us=(end - row["agreement_date"]).days,
        notes=row["notes"],
        sale_id=row["sale_id"],
        sale_no=row["sale_no"],
        sale_price=row["sale_price"],
    )
    if with_money:
        out.payable = payable_balance(conn, out.consignor_id, out.vehicle_id)
        out.recoverable = recoverable_balance(conn, out.consignor_id, out.vehicle_id)
        out.commission = -_balance(conn, "CONSIGNMENT_COMMISSION", vehicle_id=out.vehicle_id)
        out.settlements = _settlements(conn, out.id)
    return out


def get_consignment(conn: Connection, consignment_id: UUID, *, with_money: bool) -> ConsignmentOut:
    row = conn.execute(text(_CONSIGNMENTS + " where ci.id = :id"), {"id": consignment_id}).mappings().first()
    if row is None:
        raise not_found("consignment")
    return _consignment_out(conn, row, finance.tenant_info(conn).today, with_money)


def consignment_for_vehicle(conn: Connection, vehicle_id: UUID) -> UUID | None:
    value: UUID | None = conn.execute(
        text("select id from public.consignments_in where vehicle_id = :id"), {"id": vehicle_id}
    ).scalar_one_or_none()
    return value


def list_consignments(
    conn: Connection, *, status: str | None, consignor_id: UUID | None, q: str | None, with_money: bool
) -> list[ConsignmentOut]:
    today = finance.tenant_info(conn).today
    rows = conn.execute(
        text(
            _CONSIGNMENTS
            + """
             where (cast(:status as text) is null or ci.status = :status)
               and (cast(:consignor as uuid) is null or ci.consignor_id = :consignor)
               and (cast(:q as text) is null or v.stock_no ilike '%' || :q || '%' or c.name ilike '%' || :q || '%'
                    or concat_ws(' ', v.make, v.model) ilike '%' || :q || '%')
             order by (ci.status = 'ACTIVE') desc, ci.agreement_date desc, v.stock_no
            """
        ),
        {"status": status, "consignor": consignor_id, "q": q.strip() if q and q.strip() else None},
    ).mappings()
    return [_consignment_out(conn, row, today, with_money) for row in rows]


def create_consignment(conn: Connection, payload: ConsignmentIn, *, with_money: bool) -> ConsignmentOut:
    _feature_on(conn)
    consignor = customers.active_customer(conn, payload.consignor_id)
    vehicle_id = vehicles.create_vehicle(
        conn,
        payload.vehicle,
        acquisition_source="CONSIGNMENT_IN",
        ownership_type="CONSIGNED_IN",
        reason=f"استلام أمانة من {consignor.name}",
    )
    # Days with us start at the agreement (like the purchase date of an owned car, D-81).
    conn.execute(
        text("update public.vehicles set stock_date = :d where id = :id"),
        {"d": payload.agreement_date, "id": vehicle_id},
    )
    vehicles.set_status(conn, vehicle_id, "IN_PREPARATION", f"استلام أمانة من {consignor.name}")
    consignment_id = conn.execute(
        text(
            """
            insert into public.consignments_in
              (tenant_id, vehicle_id, consignor_id, agreement_date, end_date, terms_type, net_price_to_owner,
               commission_value, expenses_borne_by, shared_owner_pct, notes)
            values (private.current_tenant_id(), :vehicle_id, :consignor_id, :agreement_date, :end_date, :terms_type,
                    :net_price_to_owner, :commission_value, :expenses_borne_by, :shared_owner_pct, :notes)
            returning id
            """
        ),
        {**payload.model_dump(exclude={"vehicle"}), "vehicle_id": vehicle_id},
    ).scalar_one()
    conn.execute(
        text("update public.customers set is_consignor = true where id = :id and not is_consignor"),
        {"id": consignor.id},
    )
    return get_consignment(conn, consignment_id, with_money=with_money)


def update_terms(
    conn: Connection, consignment_id: UUID, payload: ConsignmentUpdate, *, with_money: bool
) -> ConsignmentOut:
    current = get_consignment(conn, consignment_id, with_money=False)
    if current.status != "ACTIVE":
        raise AppError("CONSIGNMENT_CLOSED", "The consignment is closed", status_code=409)
    conn.execute(
        text(
            """
            update public.consignments_in
               set agreement_date = :agreement_date, end_date = :end_date, terms_type = :terms_type,
                   net_price_to_owner = :net_price_to_owner, commission_value = :commission_value,
                   expenses_borne_by = :expenses_borne_by, shared_owner_pct = :shared_owner_pct, notes = :notes
             where id = :id
            """
        ),
        {**payload.model_dump(), "id": consignment_id},
    )
    return get_consignment(conn, consignment_id, with_money=with_money)


def return_to_owner(
    conn: Connection, consignment_id: UUID, payload: ConsignmentReturnIn, *, with_money: bool
) -> ConsignmentOut:
    """The owner takes the car back unsold. Any recoverable expenses stay owed
    (P-06 records the repayment)."""
    conn.execute(text("select 1 from public.consignments_in where id = :id for update"), {"id": consignment_id})
    current = get_consignment(conn, consignment_id, with_money=False)
    if current.status != "ACTIVE":
        raise AppError("CONSIGNMENT_CLOSED", "The consignment is closed", status_code=409)
    if payload.return_date < current.agreement_date:
        raise AppError("DATE_RANGE_INVALID", "The return is before the agreement", status_code=422)
    vehicle = vehicles.vehicle_ref(conn, current.vehicle_id, lock=True)
    if vehicle.status == "RESERVED":
        raise AppError("VEHICLE_RESERVED", "Refund or forfeit the customer's deposit first", status_code=409)
    vehicles.set_status(conn, vehicle.id, "RETURNED_TO_OWNER", f"إعادة لصاحبها: {payload.reason}")
    conn.execute(
        text("update public.consignments_in set status = 'RETURNED', returned_date = :d where id = :id"),
        {"d": payload.return_date, "id": consignment_id},
    )
    return get_consignment(conn, consignment_id, with_money=with_money)


# --- Settlements with the owner (rule 17, P-06) --------------------------------------------------------------


@dataclass(frozen=True)
class _SettlementPlan:
    consignment: ConsignmentOut
    draft: EntryDraft
    cash: finance.ActiveCashAccount
    limit: Decimal


def _plan_settlement(
    conn: Connection, info: finance.TenantInfo, consignment_id: UUID, payload: ConsignorSettlementIn
) -> _SettlementPlan:
    finance.check_entry_date(info, payload.settle_date)
    current = get_consignment(conn, consignment_id, with_money=False)
    cash = finance.active_cash_account(conn, payload.cash_account_id)
    if payload.kind == "PAYOUT":
        if current.status != "SOLD":
            raise AppError("CONSIGNMENT_NOT_SOLD", "The owner is paid after the car is sold", status_code=409)
        limit = payable_balance(conn, current.consignor_id, current.vehicle_id)
        if payload.amount > limit:
            raise AppError(
                "CONSIGNOR_OVERPAYMENT",
                "This is more than the owner is owed",
                status_code=422,
                details={"outstanding": f"{limit:.2f}"},
            )
        draft = rules.consignor_payout(
            entry_date=payload.settle_date,
            vehicle_id=current.vehicle_id,
            consignor_id=current.consignor_id,
            amount=payload.amount,
            paid_from=cash.ref,
            description=payload.notes
            or f"تسوية أمانة {current.vehicle_label} ({current.stock_no}) — {current.consignor_name}",
            source_id=None,
        )
    else:
        limit = recoverable_balance(conn, current.consignor_id, current.vehicle_id)
        if payload.amount > limit:
            raise AppError(
                "RECOVERY_EXCEEDS_EXPENSES",
                "This is more than the owner owes for expenses",
                status_code=422,
                details={"outstanding": f"{limit:.2f}"},
            )
        draft = rules.consignor_recovery(
            entry_date=payload.settle_date,
            vehicle_id=current.vehicle_id,
            consignor_id=current.consignor_id,
            amount=payload.amount,
            received_in=cash.ref,
            description=payload.notes
            or f"استرداد مصاريف أمانة {current.vehicle_label} ({current.stock_no}) من {current.consignor_name}",
            source_id=None,
        )
    return _SettlementPlan(consignment=current, draft=draft, cash=cash, limit=limit)


def preview_settlement(
    conn: Connection, consignment_id: UUID, payload: ConsignorSettlementIn, *, with_lines: bool
) -> Preview:
    info = finance.tenant_info(conn)
    plan = _plan_settlement(conn, info, consignment_id, payload)
    finance.ensure_period_open(conn, payload.settle_date)
    c = plan.consignment
    amount_ar, amount_en = _money(payload.amount, info, "ar"), _money(payload.amount, info, "en")
    rest_ar, rest_en = _money(plan.limit - payload.amount, info, "ar"), _money(plan.limit - payload.amount, info, "en")
    if payload.kind == "PAYOUT":
        summary_ar = (
            f"سيتم صرف {amount_ar} إلى {c.consignor_name} من «{plan.cash.name_ar}» عن {c.vehicle_label} "
            f"({c.stock_no}). يتبقى له {rest_ar}."
        )
        summary_en = (
            f"{amount_en} will be paid to {c.consignor_name} from “{plan.cash.name_en}” for {c.vehicle_label} "
            f"({c.stock_no}). {rest_en} will remain owed to them."
        )
        direction: Literal["IN", "OUT"] = "OUT"
    else:
        summary_ar = (
            f"سيتم استلام {amount_ar} من {c.consignor_name} في «{plan.cash.name_ar}» سداداً لمصاريف "
            f"{c.vehicle_label} ({c.stock_no}). يتبقى عليه {rest_ar}."
        )
        summary_en = (
            f"{amount_en} will be received from {c.consignor_name} into “{plan.cash.name_en}” for the expenses of "
            f"{c.vehicle_label} ({c.stock_no}). {rest_en} will remain owed by them."
        )
        direction = "IN"
    return Preview(
        summary_ar=summary_ar,
        summary_en=summary_en,
        effects=[
            PreviewEffect(
                direction=direction, label_ar=plan.cash.name_ar, label_en=plan.cash.name_en, amount=payload.amount
            )
        ],
        warnings=finance.check_cash(conn, info, plan.draft.cash_effects(), lock=False),
        lines=finance.preview_lines(conn, plan.draft) if with_lines else None,
    )


def record_settlement(
    conn: Connection, consignment_id: UUID, payload: ConsignorSettlementIn
) -> PostingResult[ConsignmentOut]:
    info = finance.tenant_info(conn)
    conn.execute(text("select 1 from public.consignments_in where id = :id for update"), {"id": consignment_id})
    plan = _plan_settlement(conn, info, consignment_id, payload)
    warnings = finance.check_cash(conn, info, plan.draft.cash_effects(), lock=True)
    settlement_id = uuid4()
    posted = engine.post(conn, replace(plan.draft, source_id=settlement_id))
    conn.execute(
        text(
            """
            insert into public.consignor_settlements
              (id, tenant_id, consignment_id, kind, settle_date, amount, cash_account_id, notes, journal_entry_id)
            values (:id, private.current_tenant_id(), :consignment, :kind, :settle_date, :amount, :cash_account_id,
                    :notes, :entry)
            """
        ),
        {**payload.model_dump(), "id": settlement_id, "consignment": consignment_id, "entry": posted.id},
    )
    return PostingResult[ConsignmentOut](
        document=get_consignment(conn, consignment_id, with_money=True),
        journal_entries=[EntryRef(id=posted.id, entry_no=posted.entry_no)],
        warnings=warnings,
    )


# --- Statements ------------------------------------------------------------------------------------------


def _statement_lines(rows: list[Any], *, sign: int) -> list[StatementLine]:
    balance = ZERO
    lines = []
    for row in rows:
        debit, credit = Decimal(row.debit), Decimal(row.credit)
        balance += (credit - debit) * sign
        lines.append(
            StatementLine(
                entry_date=row.entry_date,
                entry_no=row.entry_no,
                description=row.label,
                stock_no=row.stock_no,
                debit=debit,
                credit=credit,
                balance=balance,
            )
        )
    return lines


def consignor_statement(conn: Connection, consignor_id: UUID) -> ConsignorStatement:
    """Every 2200 and 1430 line of the owner, oldest first. The running balance is
    what the showroom owes the owner (credit 2200 raises it, debit 1430 lowers it),
    so it reconciles with the ledger by construction."""
    customer = customers.get_customer(conn, consignor_id)
    info = finance.tenant_info(conn)
    rows = list(
        conn.execute(
            text(
                """
                select e.entry_date, e.entry_no, coalesce(l.memo, e.description) as label, v.stock_no,
                       l.debit, l.credit
                  from public.journal_lines l
                  join public.journal_entries e on e.id = l.journal_entry_id
                  join public.ledger_accounts a on a.id = l.ledger_account_id
                  left join public.vehicles v on v.id = l.vehicle_id
                 where l.consignor_id = :id and a.system_key in ('CONSIGNOR_PAYABLE', 'CONSIGNOR_RECOVERABLE')
                 order by e.entry_date, e.entry_no, l.line_no
                """
            ),
            {"id": consignor_id},
        )
    )
    payable = -_balance(conn, "CONSIGNOR_PAYABLE", consignor_id=consignor_id)
    recoverable = _balance(conn, "CONSIGNOR_RECOVERABLE", consignor_id=consignor_id)
    return ConsignorStatement(
        consignor_id=customer.id,
        consignor_name=customer.name,
        consignor_phone=customer.phone_primary,
        as_of=info.today,
        currency_code=info.currency,
        lines=_statement_lines(rows, sign=1),
        payable=payable,
        recoverable=recoverable,
        net_due_to_owner=payable - recoverable,
        consignments=list_consignments(conn, status=None, consignor_id=consignor_id, q=None, with_money=True),
    )


def agreement_context(conn: Connection, consignment_id: UUID) -> dict[str, Any]:
    """Everything the printed consignment agreement shows (SPEC §4.4)."""
    consignment = get_consignment(conn, consignment_id, with_money=False)
    tenant = (
        conn.execute(
            text(
                "select t.name_ar, coalesce(t.name_en, t.name_ar) as name_en, t.address, t.phones, "
                "t.commercial_reg_no, t.currency_code, t.logo_path from public.tenants t "
                "where t.id = private.current_tenant_id()"
            )
        )
        .mappings()
        .one()
    )
    vehicle = (
        conn.execute(
            text(
                "select stock_no, make, model, trim, year, vin, plate_no, color_ext, mileage_km, asking_price "
                "from public.vehicles where id = :id"
            ),
            {"id": consignment.vehicle_id},
        )
        .mappings()
        .one()
    )
    owner = customers.get_customer(conn, consignment.consignor_id)
    return {"consignment": consignment, "tenant": dict(tenant), "vehicle": dict(vehicle), "owner": owner}


# =====================================================================================================
# Consignment OUT
# =====================================================================================================

_OUT = """
    select o.*, v.stock_no, concat_ws(' ', v.make, v.model, v.year) as vehicle_label, v.status as vehicle_status,
           x.name as external_showroom_name, s.sale_no, s.sale_price, s.sale_date
      from public.consignments_out o
      join public.vehicles v on v.id = o.vehicle_id
      join public.external_showrooms x on x.id = o.external_showroom_id
      left join public.sales s on s.id = o.sale_id
"""


def _out_row(row: Any, today: date) -> ConsignmentOutOut:
    end = row["returned_date"] or row["sale_date"] or today
    return ConsignmentOutOut.model_validate({**row, "days_out": (end - row["sent_date"]).days})


def get_out(conn: Connection, out_id: UUID) -> ConsignmentOutOut:
    row = conn.execute(text(_OUT + " where o.id = :id"), {"id": out_id}).mappings().first()
    if row is None:
        raise not_found("consignment out")
    return _out_row(row, finance.tenant_info(conn).today)


def list_out(conn: Connection, *, status: str | None, showroom_id: UUID | None) -> list[ConsignmentOutOut]:
    """“Where are my cars and for how long”: open first, longest out first."""
    today = finance.tenant_info(conn).today
    rows = conn.execute(
        text(
            _OUT
            + """
             where (cast(:status as text) is null or o.status = :status)
               and (cast(:showroom as uuid) is null or o.external_showroom_id = :showroom)
             order by (o.status = 'OUT') desc, o.sent_date, v.stock_no
            """
        ),
        {"status": status, "showroom": showroom_id},
    ).mappings()
    return [_out_row(row, today) for row in rows]


def consign_out(conn: Connection, payload: ConsignOutIn) -> ConsignmentOutOut:
    _feature_on(conn)
    info = finance.tenant_info(conn)
    if payload.sent_date > info.today:
        raise AppError("DATE_IN_FUTURE", "The date cannot be in the future", status_code=422)
    vehicle = vehicles.vehicle_ref(conn, payload.vehicle_id, lock=True)
    if vehicle.ownership_type != "OWNED":
        # Q-33 default: a consigned-in car is not re-consigned.
        raise AppError("VEHICLE_NOT_OWNED", "A consigned car cannot be sent to another showroom", status_code=422)
    if vehicle.status not in ("IN_PREPARATION", "AVAILABLE"):
        raise AppError(
            "VEHICLE_NOT_AVAILABLE",
            "Only a car in stock and not reserved can be sent out",
            status_code=409,
            details={"status": vehicle.status},
        )
    showroom = _active_showroom(conn, payload.external_showroom_id)
    out_id = conn.execute(
        text(
            """
            insert into public.consignments_out
              (tenant_id, vehicle_id, external_showroom_id, sent_date, commission_type, commission_value,
               expected_price, notes)
            values (private.current_tenant_id(), :vehicle_id, :external_showroom_id, :sent_date, :commission_type,
                    :commission_value, :expected_price, :notes)
            returning id
            """
        ),
        payload.model_dump(),
    ).scalar_one()
    reason = f"أمانة لدى {showroom.name}"
    vehicles.set_status(conn, vehicle.id, "AT_OTHER_SHOWROOM", reason)
    location = conn.execute(
        text("select id from public.locations where external_showroom_id = :id and archived_at is null"),
        {"id": showroom.id},
    ).scalar_one_or_none()
    if location is not None:
        vehicles.move(conn, vehicle.id, location, reason)
    return get_out(conn, out_id)


def _open_out(conn: Connection, out_id: UUID) -> ConsignmentOutOut:
    conn.execute(text("select 1 from public.consignments_out where id = :id for update"), {"id": out_id})
    current = get_out(conn, out_id)
    if current.status != "OUT":
        raise AppError("CONSIGNMENT_CLOSED", "The car is no longer at that showroom", status_code=409)
    return current


def return_out(conn: Connection, out_id: UUID, payload: ConsignOutReturnIn) -> ConsignmentOutOut:
    current = _open_out(conn, out_id)
    if payload.return_date < current.sent_date:
        raise AppError("DATE_RANGE_INVALID", "The return is before the car was sent", status_code=422)
    reason = payload.reason or f"عادت من {current.external_showroom_name}"
    conn.execute(
        text("update public.consignments_out set status = 'RETURNED', returned_date = :d where id = :id"),
        {"d": payload.return_date, "id": out_id},
    )
    vehicles.set_status(conn, current.vehicle_id, "AVAILABLE", reason)
    home = vehicles.default_location(conn)
    if home is not None:
        vehicles.move(conn, current.vehicle_id, home, reason)
    return get_out(conn, out_id)


# --- Sold by the external showroom (rule 18) ------------------------------------------------------------------


@dataclass(frozen=True)
class _ExternalSalePlan:
    out: ConsignmentOutOut
    vehicle: vehicles.VehicleRef
    cost: Decimal
    commission: Decimal
    sale_draft: EntryDraft
    commission_draft: EntryDraft | None
    cost_draft: EntryDraft


def _plan_external_sale(
    conn: Connection, info: finance.TenantInfo, out: ConsignmentOutOut, payload: ExternalSaleIn, *, lock: bool
) -> _ExternalSalePlan:
    finance.check_entry_date(info, payload.sale_date)
    if payload.sale_date < out.sent_date:
        raise AppError("DATE_RANGE_INVALID", "The sale is before the car was sent", status_code=422)
    vehicle = vehicles.vehicle_ref(conn, out.vehicle_id, lock=lock)
    cost = vehicles.inventory_cost(conn, vehicle.id)
    if cost <= 0:
        raise AppError("VEHICLE_COST_MISSING", "Record the purchase of this car before selling it", status_code=422)
    try:
        commission = external_commission_for(out.commission_type, payload.sale_price, out.commission_value)
    except CommissionError as exc:
        raise AppError(exc.code, str(exc), status_code=422) from exc
    label = f"{vehicle.label} ({vehicle.stock_no})"
    sale_draft = rules.external_sale(
        entry_date=payload.sale_date,
        vehicle_id=vehicle.id,
        external_showroom_id=out.external_showroom_id,
        sale_price=payload.sale_price,
        description=f"بيع {label} عن طريق {out.external_showroom_name}",
        source_id=None,
    )
    commission_draft = (
        rules.external_commission(
            entry_date=payload.sale_date,
            vehicle_id=vehicle.id,
            external_showroom_id=out.external_showroom_id,
            commission=commission,
            description=f"عمولة {out.external_showroom_name} على بيع {label}",
            source_id=None,
        )
        if commission > 0
        else None
    )
    cost_draft = rules.cost_of_sale(
        entry_date=payload.sale_date, vehicle_id=vehicle.id, cost=cost, description=f"تكلفة {label}", source_id=None
    )
    return _ExternalSalePlan(
        out=out,
        vehicle=vehicle,
        cost=cost,
        commission=commission,
        sale_draft=sale_draft,
        commission_draft=commission_draft,
        cost_draft=cost_draft,
    )


def preview_external_sale(
    conn: Connection, out_id: UUID, payload: ExternalSaleIn, *, with_lines: bool, with_profit: bool
) -> Preview:
    info = finance.tenant_info(conn)
    out = get_out(conn, out_id)
    if out.status != "OUT":
        raise AppError("CONSIGNMENT_CLOSED", "The car is no longer at that showroom", status_code=409)
    plan = _plan_external_sale(conn, info, out, payload, lock=False)
    finance.ensure_period_open(conn, payload.sale_date)
    net = payload.sale_price - plan.commission
    summary_ar = (
        f"باع {out.external_showroom_name} سيارتنا {out.vehicle_label} ({out.stock_no}) بسعر "
        f"{_money(payload.sale_price, info, 'ar')} بتاريخ {ltr(payload.sale_date.isoformat())}. "
        f"عمولته {_money(plan.commission, info, 'ar')}، ويصبح مستحقاً لنا عنده {_money(net, info, 'ar')}. "
        "تصبح السيارة مباعة ومسلّمة."
    )
    summary_en = (
        f"{out.external_showroom_name} sold our {out.vehicle_label} ({out.stock_no}) for "
        f"{_money(payload.sale_price, info, 'en')} on {payload.sale_date.isoformat()}. It keeps "
        f"{_money(plan.commission, info, 'en')}; {_money(net, info, 'en')} becomes due to us from it. "
        "The car becomes sold and delivered."
    )
    if with_profit:
        profit = net - plan.cost
        summary_ar += f" التكلفة {_money(plan.cost, info, 'ar')} والربح بعد العمولة {_money(profit, info, 'ar')}."
        summary_en += f" Cost {_money(plan.cost, info, 'en')}, profit after commission {_money(profit, info, 'en')}."
    lines = None
    if with_lines:
        lines = finance.preview_lines(conn, plan.sale_draft)
        if plan.commission_draft is not None:
            lines += finance.preview_lines(conn, plan.commission_draft)
        lines += finance.preview_lines(conn, plan.cost_draft)
    return Preview(summary_ar=summary_ar, summary_en=summary_en, effects=[], lines=lines)


def record_external_sale(
    conn: Connection, out_id: UUID, payload: ExternalSaleIn, *, user_id: UUID
) -> PostingResult[ConsignmentOutOut]:
    from app.services import sales

    info = finance.tenant_info(conn)
    out = _open_out(conn, out_id)
    plan = _plan_external_sale(conn, info, out, payload, lock=True)
    year = payload.sale_date.year
    notes = " — ".join(
        part for part in (payload.buyer_name and f"المشتري: {payload.buyer_name}", payload.notes) if part
    )
    sale_id = conn.execute(
        text(
            """
            insert into public.sales
              (tenant_id, sale_no, vehicle_id, channel, external_showroom_id, sale_date, list_price, discount,
               sale_price, external_commission, notes)
            values (private.current_tenant_id(), :sale_no, :vehicle, 'EXTERNAL_SHOWROOM', :showroom, :sale_date,
                    :price, 0, :price, :commission, :notes)
            returning id
            """
        ),
        {
            "sale_no": f"S-{year}-{sales.next_number(conn, f'sale-{year}'):04d}",
            "vehicle": out.vehicle_id,
            "showroom": out.external_showroom_id,
            "sale_date": payload.sale_date,
            "price": payload.sale_price,
            "commission": plan.commission,
            "notes": notes or None,
        },
    ).scalar_one()
    sale_entry = engine.post(conn, replace(plan.sale_draft, source_id=sale_id))
    commission_entry = (
        engine.post(conn, replace(plan.commission_draft, source_id=sale_id)) if plan.commission_draft else None
    )
    cost_entry = engine.post(conn, replace(plan.cost_draft, source_id=sale_id))
    with vehicles.vehicle_errors():
        conn.execute(
            text(
                """
                update public.sales
                   set status = 'POSTED', posted_at = now(), posted_by = :user, journal_entry_id = :entry,
                       commission_journal_entry_id = :commission_entry, cost_journal_entry_id = :cost_entry
                 where id = :id
                """
            ),
            {
                "user": user_id,
                "entry": sale_entry.id,
                "commission_entry": commission_entry.id if commission_entry else None,
                "cost_entry": cost_entry.id,
                "id": sale_id,
            },
        )
    conn.execute(
        text("update public.consignments_out set status = 'SOLD', sale_id = :sale where id = :id"),
        {"sale": sale_id, "id": out_id},
    )
    reason = f"بيعت عن طريق {out.external_showroom_name}"
    vehicles.set_status(conn, out.vehicle_id, "SOLD", reason)
    vehicles.set_status(conn, out.vehicle_id, "DELIVERED", reason)
    entries = [EntryRef(id=sale_entry.id, entry_no=sale_entry.entry_no)]
    if commission_entry is not None:
        entries.append(EntryRef(id=commission_entry.id, entry_no=commission_entry.entry_no))
    entries.append(EntryRef(id=cost_entry.id, entry_no=cost_entry.entry_no))
    allocation = distribution.allocate_sale(
        conn,
        sale_id=sale_id,
        vehicle_id=out.vehicle_id,
        sale_date=payload.sale_date,
        gross_profit=payload.sale_price - plan.commission - plan.cost,
        label=f"{out.vehicle_label} ({out.stock_no})",
    )
    if allocation is not None:
        entries.append(allocation)
    return PostingResult[ConsignmentOutOut](document=get_out(conn, out_id), journal_entries=entries)


# --- Collections from the showroom (rule 19) -------------------------------------------------------------------


def _plan_collection(
    conn: Connection, info: finance.TenantInfo, showroom_id: UUID, payload: ExternalCollectionIn
) -> tuple[EntryDraft, finance.ActiveCashAccount, ExternalShowroomOut, Decimal]:
    finance.check_entry_date(info, payload.collect_date)
    showroom = get_showroom(conn, showroom_id, with_balance=False)
    cash = finance.active_cash_account(conn, payload.cash_account_id)
    owed = showroom_receivable(conn, showroom_id)
    if payload.amount > owed:
        raise AppError(
            "EXTERNAL_OVERPAYMENT",
            "This is more than the showroom owes",
            status_code=422,
            details={"outstanding": f"{owed:.2f}"},
        )
    draft = rules.external_collection(
        entry_date=payload.collect_date,
        external_showroom_id=showroom_id,
        amount=payload.amount,
        received_in=cash.ref,
        description=payload.notes or f"تحصيل من {showroom.name}",
        source_id=None,
    )
    return draft, cash, showroom, owed


def preview_collection(
    conn: Connection, showroom_id: UUID, payload: ExternalCollectionIn, *, with_lines: bool
) -> Preview:
    info = finance.tenant_info(conn)
    draft, cash, showroom, owed = _plan_collection(conn, info, showroom_id, payload)
    finance.ensure_period_open(conn, payload.collect_date)
    rest = owed - payload.amount
    return Preview(
        summary_ar=(
            f"سيتم تحصيل {_money(payload.amount, info, 'ar')} من {showroom.name} في «{cash.name_ar}». "
            f"يتبقى عنده {_money(rest, info, 'ar')}."
        ),
        summary_en=(
            f"{_money(payload.amount, info, 'en')} will be collected from {showroom.name} into “{cash.name_en}”. "
            f"{_money(rest, info, 'en')} will remain due."
        ),
        effects=[PreviewEffect(direction="IN", label_ar=cash.name_ar, label_en=cash.name_en, amount=payload.amount)],
        lines=finance.preview_lines(conn, draft) if with_lines else None,
    )


def record_collection(
    conn: Connection, showroom_id: UUID, payload: ExternalCollectionIn
) -> PostingResult[ExternalCollectionOut]:
    info = finance.tenant_info(conn)
    conn.execute(text("select 1 from public.external_showrooms where id = :id for update"), {"id": showroom_id})
    draft, _, _, _ = _plan_collection(conn, info, showroom_id, payload)
    collection_id = uuid4()
    posted = engine.post(conn, replace(draft, source_id=collection_id))
    conn.execute(
        text(
            """
            insert into public.external_collections
              (id, tenant_id, external_showroom_id, collect_date, amount, cash_account_id, notes, journal_entry_id)
            values (:id, private.current_tenant_id(), :showroom, :collect_date, :amount, :cash_account_id, :notes,
                    :entry)
            """
        ),
        {**payload.model_dump(), "id": collection_id, "showroom": showroom_id, "entry": posted.id},
    )
    return PostingResult[ExternalCollectionOut](
        document=_collections(conn, showroom_id, collection_id)[0],
        journal_entries=[EntryRef(id=posted.id, entry_no=posted.entry_no)],
    )


def _collections(conn: Connection, showroom_id: UUID, only: UUID | None = None) -> list[ExternalCollectionOut]:
    rows = conn.execute(
        text(
            """
            select c.id, c.collect_date, c.amount, ca.name_ar as cash_account_name_ar, c.status, je.entry_no, c.notes
              from public.external_collections c
              join public.cash_accounts ca on ca.id = c.cash_account_id
              join public.journal_entries je on je.id = c.journal_entry_id
             where c.external_showroom_id = :id and (cast(:only as uuid) is null or c.id = :only)
             order by c.collect_date, je.entry_no
            """
        ),
        {"id": showroom_id, "only": only},
    ).mappings()
    return [ExternalCollectionOut.model_validate(dict(row)) for row in rows]


def showroom_statement(conn: Connection, showroom_id: UUID) -> ExternalShowroomStatement:
    """Every 1420 line of the showroom; the running balance is what it owes us."""
    showroom = get_showroom(conn, showroom_id, with_balance=False)
    info = finance.tenant_info(conn)
    rows = list(
        conn.execute(
            text(
                """
                select e.entry_date, e.entry_no, coalesce(l.memo, e.description) as label, v.stock_no,
                       l.debit, l.credit
                  from public.journal_lines l
                  join public.journal_entries e on e.id = l.journal_entry_id
                  join public.ledger_accounts a on a.id = l.ledger_account_id
                  left join public.vehicles v on v.id = l.vehicle_id
                 where l.external_showroom_id = :id and a.system_key = 'EXTERNAL_SHOWROOM_RECEIVABLE'
                 order by e.entry_date, e.entry_no, l.line_no
                """
            ),
            {"id": showroom_id},
        )
    )
    return ExternalShowroomStatement(
        external_showroom_id=showroom.id,
        name=showroom.name,
        phone=showroom.phone,
        as_of=info.today,
        currency_code=info.currency,
        lines=_statement_lines(rows, sign=-1),
        receivable=showroom_receivable(conn, showroom_id),
        cars=list_out(conn, status=None, showroom_id=showroom_id),
        collections=_collections(conn, showroom_id),
    )
