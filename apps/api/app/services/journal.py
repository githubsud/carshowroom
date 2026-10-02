"""Chart of accounts with balances, journal entries, and reversal (rule 24)."""

from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy import Connection, text

from app.core.errors import AppError, not_found
from app.domain.finance import (
    EntryRef,
    JournalEntryOut,
    JournalLineOut,
    LedgerAccountOut,
    Page,
    Preview,
    PreviewEffect,
    ReverseIn,
    ReverseOut,
)
from app.domain.ledger import ZERO, EntryDraft
from app.domain.money import format_money, ltr
from app.services import finance
from app.services.posting import engine, rules

# --- Chart of accounts ----------------------------------------------------------------------

_ACCOUNTS = text(
    """
    select a.id, a.code, p.code as parent_code, a.name_ar, a.name_en, a.type, a.normal_side, a.is_postable,
           a.subledger, coalesce(sum(l.debit - l.credit), 0) as net_debit
      from public.ledger_accounts a
      left join public.ledger_accounts p on p.id = a.parent_id
      left join public.journal_lines l
             on l.ledger_account_id = a.id and (cast(:as_of as date) is null or l.entry_date <= :as_of)
     where a.archived_at is null
     group by a.id, p.code
     order by a.code
    """
)


def list_accounts(conn: Connection, as_of: date | None) -> list[LedgerAccountOut]:
    rows = list(conn.execute(_ACCOUNTS, {"as_of": as_of}))
    # Header accounts show the total of everything beneath them.
    net: dict[str, Decimal] = {row.code: Decimal(row.net_debit) for row in rows}
    parent_of = {row.code: row.parent_code for row in rows}
    rolled: dict[str, Decimal] = dict.fromkeys(net, ZERO)
    for code, amount in net.items():
        node: str | None = code
        while node is not None:
            rolled[node] += amount
            node = parent_of.get(node)
    return [
        LedgerAccountOut(
            id=row.id,
            code=row.code,
            parent_code=row.parent_code,
            name_ar=row.name_ar,
            name_en=row.name_en,
            type=row.type,
            normal_side=row.normal_side,
            is_postable=row.is_postable,
            subledger=row.subledger,
            balance=rolled[row.code] if row.normal_side == "DEBIT" else -rolled[row.code],
        )
        for row in rows
    ]


# --- Journal entries ------------------------------------------------------------------------------

_ENTRIES = """
    select e.id, e.entry_no, e.entry_date, e.description, e.source_type, e.source_id, e.reversal_reason,
           e.is_opening, e.posted_at, ro.entry_no as reversal_of_entry_no, rb.entry_no as reversed_by_entry_no,
           (select sum(l.debit) from public.journal_lines l where l.journal_entry_id = e.id) as total
      from public.journal_entries e
      left join public.journal_entries ro on ro.id = e.reversal_of_id
      left join public.journal_entries rb on rb.id = e.reversed_by_id
"""

_LINES = text(
    """
    select l.line_no, a.code as account_code, a.name_ar as account_name_ar, a.name_en as account_name_en,
           l.debit, l.credit, ca.name_ar as cash_account_name_ar, l.memo
      from public.journal_lines l
      join public.ledger_accounts a on a.id = l.ledger_account_id
      left join public.cash_accounts ca on ca.id = l.cash_account_id
     where l.journal_entry_id = :id
     order by l.line_no
    """
)


def list_entries(
    conn: Connection,
    *,
    date_from: date | None,
    date_to: date | None,
    source_type: str | None,
    entry_no: int | None,
    page: int,
    page_size: int,
) -> Page[JournalEntryOut]:
    where = """
     where (cast(:date_from as date) is null or e.entry_date >= :date_from)
       and (cast(:date_to as date) is null or e.entry_date <= :date_to)
       and (cast(:source_type as text) is null or e.source_type = :source_type)
       and (cast(:entry_no as bigint) is null or e.entry_no = :entry_no)
    """
    params = {"date_from": date_from, "date_to": date_to, "source_type": source_type, "entry_no": entry_no}
    total = conn.execute(text("select count(*) from public.journal_entries e" + where), params).scalar_one()  # noqa: S608 - fixed SQL fragments, values are bound parameters
    rows = conn.execute(
        text(_ENTRIES + where + " order by e.entry_no desc limit :limit offset :offset"),
        {**params, "limit": page_size, "offset": (page - 1) * page_size},
    ).mappings()
    return Page[JournalEntryOut](
        items=[JournalEntryOut.model_validate(dict(row)) for row in rows],
        page=page,
        page_size=page_size,
        total=total,
    )


def get_entry(conn: Connection, entry_id: UUID) -> JournalEntryOut:
    row = conn.execute(text(_ENTRIES + " where e.id = :id"), {"id": entry_id}).mappings().first()
    if row is None:
        raise not_found("journal entry")
    entry = JournalEntryOut.model_validate(dict(row))
    entry.lines = [
        JournalLineOut.model_validate(dict(line)) for line in conn.execute(_LINES, {"id": entry_id}).mappings()
    ]
    return entry


# --- Reversal (rule 24) ------------------------------------------------------------------------------

_DOCUMENT_TABLES = {
    "GENERAL_EXPENSE": "general_expenses",
    "TRANSFER": "transfers",
    "OTHER_INCOME": "other_incomes",
    "PARTNER_CONTRIBUTION": "partner_transactions",
    "PARTNER_CAPITAL_WITHDRAWAL": "partner_transactions",
    "PARTNER_DRAWING": "partner_transactions",
    "PARTNER_LOAN": "partner_transactions",
    "PARTNER_LOAN_REPAYMENT": "partner_transactions",
    "PARTNER_LOAN_TO_BUSINESS": "partner_transactions",
    "PARTNER_LOAN_TO_BUSINESS_REPAYMENT": "partner_transactions",
    "VEHICLE_PURCHASE": "vehicle_purchases",
    "SELLER_PAYMENT": "seller_payments",
    "VEHICLE_EXPENSE": "vehicle_expenses",
    "SUPPLIER_PAYMENT": "supplier_payments",
    "CUSTOMER_REFUND": "customer_refunds",
}

# Entries tied to a document's state are undone through that document (D-75):
# a sale is cancelled, a deposit is refunded or forfeited.
_DOCUMENT_ACTIONS = {
    "SALE": "cancel the sale",
    "SALE_COST": "cancel the sale",
    "SALE_CANCELLATION": "the cancellation is final",
    "DEPOSIT": "refund or forfeit the deposit",
    "DEPOSIT_REFUND": "the deposit is settled",
    "DEPOSIT_FORFEIT": "the deposit is settled",
}


_VEHICLE_DOCUMENTS = {
    "VEHICLE_PURCHASE": """
        select v.status, 'CAPITALIZE' as treatment,
               (select count(*) from public.seller_payments s where s.purchase_id = d.id and s.status = 'POSTED')
                 as paid_later
          from public.vehicle_purchases d join public.vehicles v on v.id = d.vehicle_id where d.id = :id
    """,
    "VEHICLE_EXPENSE": """
        select v.status, d.treatment, 0 as paid_later
          from public.vehicle_expenses d join public.vehicles v on v.id = d.vehicle_id where d.id = :id
    """,
}


def _guard_document(conn: Connection, original: JournalEntryOut) -> None:
    if original.source_type in _DOCUMENT_ACTIONS:
        raise AppError(
            "USE_DOCUMENT_ACTION",
            f"This entry cannot be reversed directly: {_DOCUMENT_ACTIONS[original.source_type]}",
            status_code=409,
            details={"source_type": original.source_type},
        )
    if original.source_type not in _VEHICLE_DOCUMENTS or original.source_id is None:
        return
    row = conn.execute(text(_VEHICLE_DOCUMENTS[original.source_type]), {"id": original.source_id}).first()
    if row is None:
        return
    # A sold car's cost has moved to cost of sales; reversing a capitalized cost now would leave stock negative.
    if row.status in ("SOLD", "DELIVERED") and row.treatment == "CAPITALIZE":
        raise AppError("VEHICLE_ALREADY_SOLD", "The car is sold; cancel the sale first", status_code=409)
    if original.source_type == "VEHICLE_PURCHASE" and row.paid_later:
        raise AppError("PURCHASE_HAS_PAYMENTS", "Reverse the later payments to the seller first", status_code=409)


def _reversal_plan(conn: Connection, entry_id: UUID, reversal_date: date) -> tuple[JournalEntryOut, EntryDraft]:
    original = get_entry(conn, entry_id)
    if original.reversed_by_entry_no is not None:
        raise AppError("ENTRY_ALREADY_REVERSED", "This entry has already been reversed", status_code=409)
    if original.reversal_of_entry_no is not None:
        raise AppError("ENTRY_IS_REVERSAL", "A reversal entry cannot be reversed", status_code=409)
    _guard_document(conn, original)
    mirror = EntryDraft(
        entry_date=reversal_date,
        description=original.description,
        source_type=original.source_type,
        source_id=original.source_id,
        lines=rules.reversal_lines(engine.entry_lines(conn, entry_id)),
    )
    return original, mirror


def preview_reverse(conn: Connection, entry_id: UUID, payload: ReverseIn) -> Preview:
    info = finance.tenant_info(conn)
    reversal_date = payload.reversal_date or info.today
    finance.check_entry_date(info, reversal_date)
    finance.ensure_period_open(conn, reversal_date)
    original, mirror = _reversal_plan(conn, entry_id, reversal_date)
    warnings = finance.check_cash(conn, info, mirror.cash_effects(), lock=False)
    effects = []
    for cash_account_id, delta in mirror.cash_effects().items():
        account = finance.get_cash_account(conn, cash_account_id)
        effects.append(
            PreviewEffect(
                direction="IN" if delta > 0 else "OUT",
                label_ar=account.name_ar,
                label_en=account.name_en or account.name_ar,
                amount=abs(delta),
            )
        )
    total_ar = format_money(original.total, info.currency, "ar")
    total_en = format_money(original.total, info.currency, "en")
    return Preview(
        summary_ar=(
            f"سيتم إلغاء أثر القيد رقم {original.entry_no} ({original.description}) بقيمة {total_ar} "
            f"بقيد عكسي بتاريخ {ltr(reversal_date.isoformat())}. السبب: {payload.reason}"
        ),
        summary_en=(
            f"Entry #{original.entry_no} ({original.description}, {total_en}) will be cancelled by a reversing "
            f"entry dated {reversal_date.isoformat()}. Reason: {payload.reason}"
        ),
        effects=effects,
        warnings=warnings,
    )


def reverse(conn: Connection, entry_id: UUID, payload: ReverseIn) -> ReverseOut:
    info = finance.tenant_info(conn)
    reversal_date = payload.reversal_date or info.today
    finance.check_entry_date(info, reversal_date)
    original, mirror = _reversal_plan(conn, entry_id, reversal_date)
    warnings = finance.check_cash(conn, info, mirror.cash_effects(), lock=True)
    posted = engine.reverse(conn, entry_id, payload.reason, reversal_date)

    # The source document follows its entry (POSTED -> REVERSED).
    table = _DOCUMENT_TABLES.get(original.source_type)
    if table and original.source_id:
        conn.execute(
            text(
                # table comes from the fixed _DOCUMENT_TABLES mapping
                f"update public.{table} set status = 'REVERSED', reversal_entry_id = :reversal where id = :id"  # noqa: S608
            ),
            {"reversal": posted.id, "id": original.source_id},
        )
    return ReverseOut(
        original_entry_no=original.entry_no,
        reversal=EntryRef(id=posted.id, entry_no=posted.entry_no),
        warnings=warnings,
    )
