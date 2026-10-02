"""Installments (SPEC §4.8): schedules, plans created when an installment sale
is posted (rule 13, mode a), receipts allocated oldest-first (rule 15), the
due/overdue board, and the customer installment statement.

Paid and remaining are always derived from allocations of receipts that still
count (business rule 4): the installment_status view.
"""

from collections import defaultdict
from dataclasses import dataclass, replace
from datetime import date, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Connection, text

from app.core.errors import AppError, not_found
from app.domain.finance import EntryRef, PostingResult, Preview, PreviewEffect
from app.domain.installments import (
    AllocationOut,
    CustomerInstallmentStatement,
    CustomerOutstanding,
    InstallmentBoard,
    InstallmentKpis,
    InstallmentOut,
    InstallmentPlanIn,
    InstallmentPlanOut,
    InstallmentState,
    PaperOut,
    ReceiptIn,
    ReceiptOut,
    ScheduleRowOut,
)
from app.domain.ledger import ZERO, EntryDraft
from app.domain.money import format_money, ltr
from app.domain.schedule import ScheduleError, ScheduleRow, equal_schedule, validate_manual
from app.services import customers, finance
from app.services.posting import engine, rules

# --- Schedules ---------------------------------------------------------------------------


def build_schedule(financed: Decimal, plan: InstallmentPlanIn) -> list[ScheduleRow]:
    try:
        if plan.frequency == "MANUAL":
            rows = [ScheduleRow(i + 1, r.due_date, r.amount) for i, r in enumerate(plan.schedule or [])]
            validate_manual(financed, rows)
            return rows
        if plan.count is None or plan.first_due_date is None:  # guarded by the model validator
            raise ScheduleError("give the number of installments and the first due date")
        return equal_schedule(financed, plan.count, plan.first_due_date, plan.frequency)
    except ScheduleError as exc:
        raise AppError(
            "INSTALLMENT_SCHEDULE_MISMATCH", str(exc), status_code=422, details={"financed": f"{financed:.2f}"}
        ) from exc


def preview_schedule(financed: Decimal, plan: InstallmentPlanIn) -> list[ScheduleRowOut]:
    return [ScheduleRowOut(seq=r.seq, due_date=r.due_date, amount=r.amount) for r in build_schedule(financed, plan)]


def create_plan(
    conn: Connection,
    *,
    sale_id: UUID,
    customer_id: UUID,
    financed: Decimal,
    plan: InstallmentPlanIn,
    schedule: list[ScheduleRow],
) -> UUID:
    plan_id = uuid4()
    conn.execute(
        text(
            """
            insert into public.installment_plans
              (id, tenant_id, sale_id, customer_id, mode, financed_amount, frequency, installment_count, first_due_date)
            values (:id, private.current_tenant_id(), :sale_id, :customer_id, 'A', :financed, :frequency, :count,
                    :first_due_date)
            """
        ),
        {
            "id": plan_id,
            "sale_id": sale_id,
            "customer_id": customer_id,
            "financed": financed,
            "frequency": plan.frequency,
            "count": len(schedule),
            "first_due_date": schedule[0].due_date,
        },
    )
    for row in schedule:
        conn.execute(
            text(
                "insert into public.installments (tenant_id, plan_id, seq, due_date, amount_due) "
                "values (private.current_tenant_id(), :plan, :seq, :due, :amount)"
            ),
            {"plan": plan_id, "seq": row.seq, "due": row.due_date, "amount": row.amount},
        )
    return plan_id


# --- Reading installments ------------------------------------------------------------------------

_INSTALLMENTS = """
    select s.id, s.plan_id, s.sale_id, sa.sale_no, s.customer_id, c.name as customer_name,
           c.phone_primary as customer_phone, v.stock_no, concat_ws(' ', v.make, v.model, v.year) as vehicle_label,
           s.seq, s.due_date, s.amount_due, s.paid, s.remaining, s.plan_status,
           exists (select 1 from public.deferred_papers d
                    where d.customer_id = s.customer_id and d.status = 'BOUNCED') as customer_bounced
      from public.installment_status s
      join public.sales sa on sa.id = s.sale_id
      join public.vehicles v on v.id = sa.vehicle_id
      join public.customers c on c.id = s.customer_id
"""


def _state(row: Any, today: date) -> InstallmentState:
    if row.plan_status == "CANCELLED":
        return "CANCELLED"
    if row.remaining <= 0:
        return "PAID"
    if row.due_date < today:
        return "OVERDUE"
    if row.due_date == today:
        return "DUE_TODAY"
    return "UPCOMING"


def _installment(row: Any, today: date) -> InstallmentOut:
    state = _state(row, today)
    return InstallmentOut(
        id=row.id,
        plan_id=row.plan_id,
        sale_id=row.sale_id,
        sale_no=row.sale_no,
        customer_id=row.customer_id,
        customer_name=row.customer_name,
        customer_phone=row.customer_phone,
        stock_no=row.stock_no,
        vehicle_label=row.vehicle_label,
        seq=row.seq,
        due_date=row.due_date,
        amount_due=row.amount_due,
        paid=row.paid,
        remaining=row.remaining,
        days_late=(today - row.due_date).days if state == "OVERDUE" else 0,
        state=state,
        customer_bounced=row.customer_bounced,
    )


def list_installments(
    conn: Connection,
    *,
    view: str,
    days: int,
    customer_id: UUID | None,
    date_from: date | None,
    date_to: date | None,
) -> list[InstallmentOut]:
    today = finance.tenant_info(conn).today
    where = ["(cast(:customer as uuid) is null or s.customer_id = :customer)"]
    params: dict[str, Any] = {"customer": customer_id, "today": today, "until": today + timedelta(days=days)}
    if view == "calendar":
        where.append("s.due_date between :date_from and :date_to and s.plan_status = 'ACTIVE'")
        params.update(date_from=date_from or today.replace(day=1), date_to=date_to or today + timedelta(days=31))
    else:
        where.append("s.plan_status = 'ACTIVE' and s.remaining > 0")
        if view == "due_today":
            where.append("s.due_date = :today")
        elif view == "upcoming":
            where.append("s.due_date between :today and :until")
        elif view == "overdue":
            where.append("s.due_date < :today")
    rows = conn.execute(
        text(_INSTALLMENTS + " where " + " and ".join(where) + " order by s.due_date, c.name, s.seq"), params
    )
    return [_installment(row, today) for row in rows]


def board(conn: Connection, *, view: str, days: int, customer_id: UUID | None) -> InstallmentBoard:
    today = finance.tenant_info(conn).today
    open_rows = list_installments(conn, view="open", days=days, customer_id=customer_id, date_from=None, date_to=None)
    shown = [r for r in open_rows if _in_view(r, view, today, days)]
    per_customer: dict[UUID, CustomerOutstanding] = {}
    for r in open_rows:
        entry = per_customer.get(r.customer_id) or CustomerOutstanding(
            customer_id=r.customer_id,
            customer_name=r.customer_name,
            customer_phone=r.customer_phone,
            outstanding=ZERO,
            overdue=ZERO,
            bounced=r.customer_bounced,
        )
        entry.outstanding += r.remaining
        if r.state == "OVERDUE":
            entry.overdue += r.remaining
        per_customer[r.customer_id] = entry
    return InstallmentBoard(
        as_of=today,
        due_today=sum((r.remaining for r in open_rows if r.state == "DUE_TODAY"), ZERO),
        due_soon=sum((r.remaining for r in open_rows if today <= r.due_date <= today + timedelta(days=days)), ZERO),
        overdue=sum((r.remaining for r in open_rows if r.state == "OVERDUE"), ZERO),
        rows=shown,
        customers=sorted(per_customer.values(), key=lambda c: (-c.overdue, -c.outstanding)),
    )


def _in_view(row: InstallmentOut, view: str, today: date, days: int) -> bool:
    if view == "due_today":
        return row.state == "DUE_TODAY"
    if view == "upcoming":
        return today <= row.due_date <= today + timedelta(days=days)
    if view == "overdue":
        return row.state == "OVERDUE"
    return True


def kpis(conn: Connection) -> InstallmentKpis:
    today = finance.tenant_info(conn).today
    rows = list_installments(conn, view="open", days=7, customer_id=None, date_from=None, date_to=None)
    within_48h = [r for r in rows if today <= r.due_date <= today + timedelta(days=2)]
    within_7d = [r for r in rows if today <= r.due_date <= today + timedelta(days=7)]
    overdue = [r for r in rows if r.state == "OVERDUE"]
    bounced = conn.execute(text("select count(*) from public.deferred_papers where status = 'BOUNCED'")).scalar_one()
    return InstallmentKpis(
        due_48h=sum((r.remaining for r in within_48h), ZERO),
        due_48h_count=len(within_48h),
        due_7d=sum((r.remaining for r in within_7d), ZERO),
        due_7d_count=len(within_7d),
        overdue=sum((r.remaining for r in overdue), ZERO),
        overdue_count=len(overdue),
        bounced_count=bounced,
    )


# --- Plans ---------------------------------------------------------------------------------------------

_PLANS = """
    select p.id, p.sale_id, sa.sale_no, p.customer_id, c.name as customer_name, v.stock_no,
           concat_ws(' ', v.make, v.model, v.year) as vehicle_label, p.financed_amount, p.frequency,
           p.installment_count, p.first_due_date, p.status
      from public.installment_plans p
      join public.sales sa on sa.id = p.sale_id
      join public.vehicles v on v.id = sa.vehicle_id
      join public.customers c on c.id = p.customer_id
"""


def plan_id_for_sale(conn: Connection, sale_id: UUID) -> UUID | None:
    return conn.execute(
        text("select id from public.installment_plans where sale_id = :id"), {"id": sale_id}
    ).scalar_one_or_none()


def _receipts(conn: Connection, plan_id: UUID) -> list[ReceiptOut]:
    rows = conn.execute(
        text(
            """
            select r.id, r.receipt_date, r.amount, r.source, ca.name_ar as cash_account_name_ar, r.excess_to_credit,
                   r.status, je.entry_no
              from public.customer_receipts r
              left join public.cash_accounts ca on ca.id = r.cash_account_id
              join public.journal_entries je on je.id = r.journal_entry_id
             where r.plan_id = :plan
             order by r.receipt_date, je.entry_no
            """
        ),
        {"plan": plan_id},
    ).fetchall()
    allocations: dict[UUID, list[AllocationOut]] = defaultdict(list)
    for a in conn.execute(
        text(
            """
            select ip.receipt_id, i.seq, ip.amount
              from public.installment_payments ip join public.installments i on i.id = ip.installment_id
             where i.plan_id = :plan order by i.seq
            """
        ),
        {"plan": plan_id},
    ):
        allocations[a.receipt_id].append(AllocationOut(seq=a.seq, amount=a.amount))
    return [ReceiptOut.model_validate({**r._mapping, "allocations": allocations[r.id]}) for r in rows]


def get_plan(conn: Connection, plan_id: UUID, *, with_papers: bool) -> InstallmentPlanOut:
    from app.services import papers  # papers imports this module, so import it here

    today = finance.tenant_info(conn).today
    row = conn.execute(text(_PLANS + " where p.id = :id"), {"id": plan_id}).mappings().first()
    if row is None:
        raise not_found("installment plan")
    rows = [
        _installment(r, today)
        for r in conn.execute(text(_INSTALLMENTS + " where s.plan_id = :plan order by s.seq"), {"plan": plan_id})
    ]
    paper_rows: list[PaperOut] = papers.list_papers(conn, plan_id=plan_id) if with_papers else []
    return InstallmentPlanOut(
        **row,
        paid_total=sum((r.paid for r in rows), ZERO),
        remaining_total=sum((r.remaining for r in rows if r.state != "CANCELLED"), ZERO),
        overdue_total=sum((r.remaining for r in rows if r.state == "OVERDUE"), ZERO),
        installments=rows,
        receipts=_receipts(conn, plan_id),
        papers=paper_rows,
    )


def collected(conn: Connection, plan_id: UUID) -> Decimal:
    """What the buyer has paid towards the plan through receipts that still count."""
    return Decimal(
        conn.execute(
            text("select coalesce(sum(paid), 0) from public.installment_status where plan_id = :plan"),
            {"plan": plan_id},
        ).scalar_one()
    )


def cancel_plan(conn: Connection, plan_id: UUID) -> None:
    conn.execute(text("update public.installment_plans set status = 'CANCELLED' where id = :id"), {"id": plan_id})


# --- Receipts (rule 15) -----------------------------------------------------------------------------------


@dataclass(frozen=True)
class _ReceiptPlan:
    draft: EntryDraft
    plan: Any
    allocations: list[tuple[UUID, int, Decimal]]
    excess: Decimal
    cash: finance.ActiveCashAccount | None


def allocate(
    conn: Connection, plan_id: UUID, amount: Decimal, *, first_installment: UUID | None = None
) -> tuple[list[tuple[UUID, int, Decimal]], Decimal]:
    """Oldest first (BACKLOG 5.4); a cheque pays its own installment first. Returns
    the allocations and whatever is left over."""
    rows = conn.execute(
        text(
            "select id, seq, remaining from public.installment_status "
            "where plan_id = :plan and remaining > 0 order by (id = cast(:first as uuid)) desc, due_date, seq"
        ),
        {"plan": plan_id, "first": first_installment},
    ).fetchall()
    left = amount
    allocations = []
    for row in rows:
        if left <= 0:
            break
        part = min(left, Decimal(row.remaining))
        allocations.append((row.id, row.seq, part))
        left -= part
    return allocations, left


def plan_receipt(
    conn: Connection,
    info: finance.TenantInfo,
    plan_id: UUID,
    *,
    receipt_date: date,
    amount: Decimal,
    received_in: finance.ActiveCashAccount | None,
    keep_excess_as_credit: bool,
    description: str | None,
    first_installment: UUID | None = None,
) -> _ReceiptPlan:
    finance.check_entry_date(info, receipt_date)
    plan = conn.execute(text(_PLANS + " where p.id = :id"), {"id": plan_id}).first()
    if plan is None:
        raise not_found("installment plan")
    if plan.status != "ACTIVE":
        # Business rule 2: no new payments against a cancelled sale.
        raise AppError("SALE_CANCELLED", "The sale was cancelled; no more payments are taken", status_code=409)
    allocations, excess = allocate(conn, plan_id, amount, first_installment=first_installment)
    outstanding = amount - excess
    if excess > 0:
        policy = conn.execute(text("select overpayment_policy from public.tenant_settings")).scalar_one()
        if received_in is None or policy != "ALLOW_AS_CREDIT" or not keep_excess_as_credit:
            # Business rule 3 (D-41: BLOCK unless the showroom allows credit and the user ticks it).
            raise AppError(
                "PAYMENT_EXCEEDS_OUTSTANDING",
                "The payment is more than what is still owed",
                status_code=422,
                details={"outstanding": f"{outstanding:.2f}", "policy": policy},
            )
    if outstanding <= 0:
        raise AppError("NOTHING_OWED", "Nothing is owed on this plan", status_code=422)
    if received_in is None:
        owed = customers.credit_owed(conn, plan.customer_id)
        if amount > owed:
            raise AppError(
                "CREDIT_INSUFFICIENT",
                "The customer's credit is less than this amount",
                status_code=422,
                details={"credit_owed": f"{owed:.2f}"},
            )
    seqs = ", ".join(str(seq) for _, seq, _ in allocations)
    draft = rules.installment_receipt(
        entry_date=receipt_date,
        customer_id=plan.customer_id,
        allocated=outstanding,
        received_in=received_in.ref if received_in else None,
        excess_to_credit=excess,
        description=description or f"تحصيل قسط ({seqs}) — {plan.sale_no} — {plan.customer_name}",
        source_id=None,
    )
    return _ReceiptPlan(draft=draft, plan=plan, allocations=allocations, excess=excess, cash=received_in)


def _received_in(conn: Connection, payload: ReceiptIn) -> finance.ActiveCashAccount | None:
    return finance.active_cash_account(conn, payload.cash_account_id) if payload.cash_account_id else None


def preview_receipt(conn: Connection, plan_id: UUID, payload: ReceiptIn, *, with_lines: bool) -> Preview:
    info = finance.tenant_info(conn)
    plan = plan_receipt(
        conn,
        info,
        plan_id,
        receipt_date=payload.receipt_date,
        amount=payload.amount,
        received_in=_received_in(conn, payload),
        keep_excess_as_credit=payload.keep_excess_as_credit,
        description=payload.notes,
    )
    finance.ensure_period_open(conn, payload.receipt_date)
    parts_ar = "، ".join(f"القسط {seq}: {format_money(a, info.currency, 'ar')}" for _, seq, a in plan.allocations)
    parts_en = ", ".join(f"installment {seq}: {format_money(a, info.currency, 'en')}" for _, seq, a in plan.allocations)
    where_ar = f"في «{plan.cash.name_ar}»" if plan.cash else "من رصيده الدائن"
    where_en = f"into “{plan.cash.name_en}”" if plan.cash else "from their credit"
    summary_ar = (
        f"سيتم تحصيل {format_money(payload.amount, info.currency, 'ar')} من {plan.plan.customer_name} {where_ar} "
        f"بتاريخ {ltr(payload.receipt_date.isoformat())}: {parts_ar}."
    )
    summary_en = (
        f"{format_money(payload.amount, info.currency, 'en')} from {plan.plan.customer_name} will be received "
        f"{where_en} on {payload.receipt_date.isoformat()}: {parts_en}."
    )
    if plan.excess > 0:
        summary_ar += f" الزيادة {format_money(plan.excess, info.currency, 'ar')} تبقى رصيداً للعميل."
        summary_en += f" The extra {format_money(plan.excess, info.currency, 'en')} stays as the customer's credit."
    return Preview(
        summary_ar=summary_ar,
        summary_en=summary_en,
        effects=(
            [
                PreviewEffect(
                    direction="IN", label_ar=plan.cash.name_ar, label_en=plan.cash.name_en, amount=payload.amount
                )
            ]
            if plan.cash
            else []
        ),
        lines=finance.preview_lines(conn, plan.draft) if with_lines else None,
    )


def post_receipt(
    conn: Connection,
    plan: _ReceiptPlan,
    *,
    receipt_date: date,
    amount: Decimal,
    source: str,
    cash_account_id: UUID | None,
    deferred_paper_id: UUID | None,
    notes: str | None,
) -> tuple[UUID, engine.PostedEntry]:
    receipt_id = uuid4()
    posted = engine.post(conn, replace(plan.draft, source_id=receipt_id))
    conn.execute(
        text(
            """
            insert into public.customer_receipts
              (id, tenant_id, customer_id, plan_id, receipt_date, amount, source, cash_account_id, deferred_paper_id,
               excess_to_credit, notes, journal_entry_id)
            values (:id, private.current_tenant_id(), :customer, :plan, :d, :amount, :source, :cash, :paper, :excess,
                    :notes, :entry)
            """
        ),
        {
            "id": receipt_id,
            "customer": plan.plan.customer_id,
            "plan": plan.plan.id,
            "d": receipt_date,
            "amount": amount,
            "source": source,
            "cash": cash_account_id,
            "paper": deferred_paper_id,
            "excess": plan.excess,
            "notes": notes,
            "entry": posted.id,
        },
    )
    for installment_id, _, part in plan.allocations:
        conn.execute(
            text(
                "insert into public.installment_payments (tenant_id, receipt_id, installment_id, amount) "
                "values (private.current_tenant_id(), :receipt, :installment, :amount)"
            ),
            {"receipt": receipt_id, "installment": installment_id, "amount": part},
        )
    return receipt_id, posted


def record_receipt(conn: Connection, plan_id: UUID, payload: ReceiptIn) -> PostingResult[InstallmentPlanOut]:
    info = finance.tenant_info(conn)
    # Serialise payments on one plan: two cashiers cannot pay the same installment twice.
    conn.execute(text("select 1 from public.installment_plans where id = :id for update"), {"id": plan_id})
    received_in = _received_in(conn, payload)
    plan = plan_receipt(
        conn,
        info,
        plan_id,
        receipt_date=payload.receipt_date,
        amount=payload.amount,
        received_in=received_in,
        keep_excess_as_credit=payload.keep_excess_as_credit,
        description=payload.notes,
    )
    warnings = finance.check_cash(conn, info, plan.draft.cash_effects(), lock=True)
    _, posted = post_receipt(
        conn,
        plan,
        receipt_date=payload.receipt_date,
        amount=payload.amount,
        source=payload.source,
        cash_account_id=payload.cash_account_id,
        deferred_paper_id=None,
        notes=payload.notes,
    )
    return PostingResult[InstallmentPlanOut](
        document=get_plan(conn, plan_id, with_papers=False),
        journal_entries=[EntryRef(id=posted.id, entry_no=posted.entry_no)],
        warnings=warnings,
    )


# --- Customer statement (BACKLOG 5.8) ----------------------------------------------------------------------


def customer_statement(conn: Connection, customer_id: UUID) -> CustomerInstallmentStatement:
    customer = customers.get_customer(conn, customer_id)
    info = finance.tenant_info(conn)
    plan_ids = conn.execute(
        text(
            "select p.id from public.installment_plans p join public.sales s on s.id = p.sale_id "
            "where p.customer_id = :id order by s.sale_date, s.sale_no"
        ),
        {"id": customer_id},
    ).scalars()
    plans = [get_plan(conn, plan_id, with_papers=True) for plan_id in plan_ids]
    active = [p for p in plans if p.status == "ACTIVE"]
    return CustomerInstallmentStatement(
        customer_id=customer.id,
        customer_name=customer.name,
        customer_phone=customer.phone_primary,
        as_of=info.today,
        currency_code=info.currency,
        plans=plans,
        total_financed=sum((p.financed_amount for p in active), ZERO),
        total_paid=sum((p.paid_total for p in active), ZERO),
        total_remaining=sum((p.remaining_total for p in active), ZERO),
        total_overdue=sum((p.overdue_total for p in active), ZERO),
    )
