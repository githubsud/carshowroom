"""Suppliers and workshops (D-23): records, what the showroom owes them
(payable to suppliers, rule 31), their statement, and payments (rule 32)."""

from dataclasses import replace
from datetime import date
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import Connection, text

from app.core.errors import AppError, not_found
from app.core.phone import normalize_phone
from app.domain.finance import EntryRef, PostingResult, Preview, PreviewEffect
from app.domain.ledger import EntryDraft
from app.domain.money import format_money, ltr
from app.domain.vehicles import (
    StatementRow,
    SupplierIn,
    SupplierOut,
    SupplierPaymentIn,
    SupplierPaymentOut,
    SupplierStatementOut,
    SupplierUpdate,
)
from app.services import customers, finance
from app.services.posting import engine, rules

_BALANCE = """
    coalesce((select sum(l.credit - l.debit)
                from public.journal_lines l join public.ledger_accounts a on a.id = l.ledger_account_id
               where l.supplier_id = s.id and a.system_key = 'SUPPLIER_PAYABLE'
                 and (cast(:as_of as date) is null or l.entry_date <= :as_of)), 0)
"""
_SUPPLIERS = f"""
    select s.id, s.name, s.kind, s.phone, s.notes, s.archived_at is not null as archived, {_BALANCE} as balance
      from public.suppliers s
"""  # noqa: S608 - fixed SQL fragments


def list_suppliers(conn: Connection, include_archived: bool = False) -> list[SupplierOut]:
    where = "" if include_archived else " where s.archived_at is null"
    rows = conn.execute(text(_SUPPLIERS + where + " order by s.name"), {"as_of": None}).mappings()
    return [SupplierOut.model_validate(dict(row)) for row in rows]


def get_supplier(conn: Connection, supplier_id: UUID, as_of: date | None = None) -> SupplierOut:
    row = conn.execute(text(_SUPPLIERS + " where s.id = :id"), {"id": supplier_id, "as_of": as_of}).mappings().first()
    if row is None:
        raise not_found("supplier")
    return SupplierOut.model_validate(dict(row))


def active_supplier(conn: Connection, supplier_id: UUID) -> SupplierOut:
    supplier = (
        conn.execute(text(_SUPPLIERS + " where s.id = :id"), {"id": supplier_id, "as_of": None}).mappings().first()
    )
    if supplier is None or supplier["archived"]:
        raise AppError("SUPPLIER_INVALID", "Unknown or archived supplier", status_code=422)
    return SupplierOut.model_validate(dict(supplier))


def create_supplier(conn: Connection, payload: SupplierIn) -> SupplierOut:
    phone = normalize_phone(payload.phone, customers.country_code(conn)) if payload.phone else None
    new_id = conn.execute(
        text(
            "insert into public.suppliers (tenant_id, name, kind, phone, notes) "
            "values (private.current_tenant_id(), :name, :kind, :phone, :notes) returning id"
        ),
        {**payload.model_dump(), "phone": phone},
    ).scalar_one()
    return get_supplier(conn, new_id)


def update_supplier(conn: Connection, supplier_id: UUID, changes: SupplierUpdate) -> SupplierOut:
    current = get_supplier(conn, supplier_id)
    values: dict[str, object] = changes.model_dump(exclude_unset=True, exclude={"archived"})
    if values.get("phone"):
        values["phone"] = normalize_phone(str(values["phone"]), customers.country_code(conn))
    if changes.archived is True and current.balance != 0:
        raise AppError("SUPPLIER_NOT_SETTLED", "A supplier with an open balance cannot be archived", status_code=409)
    if changes.archived is not None:
        conn.execute(
            text("update public.suppliers set archived_at = case when :archived then now() end where id = :id"),
            {"archived": changes.archived, "id": supplier_id},
        )
    if values:
        assignments = ", ".join(f"{column} = :{column}" for column in values)  # keys from a StrictModel
        conn.execute(
            text(f"update public.suppliers set {assignments} where id = :id"),  # noqa: S608
            {**values, "id": supplier_id},
        )
    return get_supplier(conn, supplier_id)


# --- Statement ---------------------------------------------------------------------------------------

_LINES = text(
    """
    select e.entry_date, e.entry_no, e.description, e.source_type, l.debit, l.credit,
           e.reversal_of_id is not null as is_reversal, e.reversed_by_id is not null as reversed
      from public.journal_lines l
      join public.journal_entries e on e.id = l.journal_entry_id
      join public.ledger_accounts a on a.id = l.ledger_account_id
     where l.supplier_id = :id and a.system_key = 'SUPPLIER_PAYABLE' and l.entry_date between :date_from and :date_to
     order by l.entry_date, e.entry_no, l.line_no
    """
)


def statement(conn: Connection, supplier_id: UUID, date_from: date, date_to: date) -> SupplierStatementOut:
    if date_from > date_to:
        raise AppError("DATE_RANGE_INVALID", "The start date is after the end date", status_code=422)
    supplier = get_supplier(conn, supplier_id)
    opening = Decimal(
        conn.execute(
            text(
                """
                select coalesce(sum(l.credit - l.debit), 0)
                  from public.journal_lines l join public.ledger_accounts a on a.id = l.ledger_account_id
                 where l.supplier_id = :id and a.system_key = 'SUPPLIER_PAYABLE' and l.entry_date < :date_from
                """
            ),
            {"id": supplier_id, "date_from": date_from},
        ).scalar_one()
    )
    balance = opening
    lines = []
    for row in conn.execute(_LINES, {"id": supplier_id, "date_from": date_from, "date_to": date_to}):
        balance += row.credit - row.debit
        lines.append(
            StatementRow(
                entry_date=row.entry_date,
                entry_no=row.entry_no,
                description=row.description,
                source_type=row.source_type,
                amount_owed=row.credit,
                amount_paid=row.debit,
                balance=balance,
                reversed=row.reversed,
                is_reversal=row.is_reversal,
            )
        )
    return SupplierStatementOut(
        supplier=supplier,
        date_from=date_from,
        date_to=date_to,
        currency_code=finance.tenant_info(conn).currency,
        opening_balance=opening,
        closing_balance=balance,
        lines=lines,
    )


# --- Payments (rule 32) ---------------------------------------------------------------------------------


def _plan_payment(
    conn: Connection, info: finance.TenantInfo, supplier: SupplierOut, payload: SupplierPaymentIn
) -> tuple[EntryDraft, finance.ActiveCashAccount]:
    finance.check_entry_date(info, payload.payment_date)
    if payload.amount > supplier.balance:
        # Like a loan repayment (D-63): never pay more than is owed.
        raise AppError(
            "PAYMENT_EXCEEDS_BALANCE",
            "The payment is more than the showroom owes",
            status_code=422,
            details={"outstanding": f"{supplier.balance:.2f}"},
        )
    cash = finance.active_cash_account(conn, payload.cash_account_id)
    draft = rules.supplier_payment(
        entry_date=payload.payment_date,
        supplier_id=supplier.id,
        amount=payload.amount,
        paid_from=cash.ref,
        description=payload.notes or f"سداد للمورد {supplier.name}",
        source_id=None,
    )
    return draft, cash


def preview_payment(conn: Connection, supplier_id: UUID, payload: SupplierPaymentIn, *, with_lines: bool) -> Preview:
    info = finance.tenant_info(conn)
    supplier = get_supplier(conn, supplier_id)
    draft, cash = _plan_payment(conn, info, supplier, payload)
    finance.ensure_period_open(conn, payload.payment_date)
    warnings = finance.check_cash(conn, info, draft.cash_effects(), lock=False)
    remaining = supplier.balance - payload.amount
    return Preview(
        summary_ar=(
            f"سيتم دفع {format_money(payload.amount, info.currency, 'ar')} من «{cash.name_ar}» للمورد {supplier.name} "
            f"بتاريخ {ltr(payload.payment_date.isoformat())}. "
            f"المتبقي له: {format_money(remaining, info.currency, 'ar')}."
        ),
        summary_en=(
            f"{format_money(payload.amount, info.currency, 'en')} will be paid from “{cash.name_en}” to "
            f"{supplier.name} on {payload.payment_date.isoformat()}. Still owed: "
            f"{format_money(remaining, info.currency, 'en')}."
        ),
        effects=[PreviewEffect(direction="OUT", label_ar=cash.name_ar, label_en=cash.name_en, amount=payload.amount)],
        warnings=warnings,
        lines=finance.preview_lines(conn, draft) if with_lines else None,
    )


def record_payment(
    conn: Connection, supplier_id: UUID, payload: SupplierPaymentIn
) -> PostingResult[SupplierPaymentOut]:
    info = finance.tenant_info(conn)
    conn.execute(text("select 1 from public.suppliers where id = :id for update"), {"id": supplier_id})
    supplier = get_supplier(conn, supplier_id)
    draft, _ = _plan_payment(conn, info, supplier, payload)
    warnings = finance.check_cash(conn, info, draft.cash_effects(), lock=True)
    document_id = uuid4()
    posted = engine.post(conn, replace(draft, source_id=document_id))
    conn.execute(
        text(
            """
            insert into public.supplier_payments
              (id, tenant_id, supplier_id, payment_date, amount, cash_account_id, notes, journal_entry_id)
            values (:id, private.current_tenant_id(), :supplier_id, :payment_date, :amount, :cash_account_id, :notes,
                    :journal_entry_id)
            """
        ),
        {**payload.model_dump(), "id": document_id, "supplier_id": supplier_id, "journal_entry_id": posted.id},
    )
    return PostingResult[SupplierPaymentOut](
        document=SupplierPaymentOut(
            id=document_id,
            supplier_id=supplier_id,
            payment_date=payload.payment_date,
            amount=payload.amount,
            cash_account_id=payload.cash_account_id,
            status="POSTED",
            entry_no=posted.entry_no,
        ),
        journal_entries=[EntryRef(id=posted.id, entry_no=posted.entry_no)],
        warnings=warnings,
    )
