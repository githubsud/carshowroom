"""Deferred papers register (سجل الأوراق الآجلة, SPEC §4.8, D-24): promissory
notes and post-dated cheques, their physical life, and their money effects:

* COLLECT (a cheque cleared or a note paid): a receipt (rule 15) allocated to
  the paper's installment first (A-10: a cheque reaches the ledger only now).
* BOUNCE after collection: rule 27 reopens the balance, plus optional bank
  charges (P-07); before collection a bounce is status-only (A-10).
* Every change is an event; OVERDUE is derived, never stored (C-10).
"""

from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Connection, text
from sqlalchemy.exc import DBAPIError, IntegrityError

from app.core.errors import AppError, not_found
from app.domain.finance import EntryRef, PostingResult, PostingWarning, Preview, PreviewEffect
from app.domain.installments import PaperActionIn, PaperEventOut, PaperIn, PaperOut
from app.domain.ledger import ZERO, EntryDraft
from app.domain.money import format_money, ltr
from app.services import customers, finance, installments, notifications
from app.services.posting import engine, rules

_NEXT = {
    "DEPOSIT": "DEPOSITED",
    "COLLECT": "COLLECTED",
    "BOUNCE": "BOUNCED",
    "RETURN": "RETURNED",
    "DEFAULT": "DEFAULTED",
    "LEGAL": "LEGAL",
}

_PAPERS = """
    select d.id, d.paper_type, d.number, d.customer_id, c.name as customer_name, d.installment_id,
           i.seq as installment_seq, s.sale_no, d.amount, d.issue_date, d.due_date, d.status, d.storage_location,
           d.drawer_bank, d.drawer_branch, d.account_holder, d.notes, d.receipt_id, i.plan_id
      from public.deferred_papers d
      join public.customers c on c.id = d.customer_id
      left join public.installments i on i.id = d.installment_id
      left join public.installment_plans p on p.id = i.plan_id
      left join public.sales s on s.id = p.sale_id
"""


def _paper(row: Any, today: Any, events: list[PaperEventOut] | None = None) -> PaperOut:
    data = dict(row._mapping)
    data.pop("receipt_id")
    data.pop("plan_id")
    data["overdue"] = data["status"] in ("HELD", "DEPOSITED") and data["due_date"] < today
    return PaperOut(**data, events=events or [])


def list_papers(
    conn: Connection,
    *,
    plan_id: UUID | None = None,
    status: str | None = None,
    paper_type: str | None = None,
    customer_id: UUID | None = None,
    overdue_only: bool = False,
) -> list[PaperOut]:
    today = finance.tenant_info(conn).today
    rows = conn.execute(
        text(
            _PAPERS
            + """
             where (cast(:plan as uuid) is null or i.plan_id = :plan)
               and (cast(:status as text) is null or d.status = :status)
               and (cast(:type as text) is null or d.paper_type = :type)
               and (cast(:customer as uuid) is null or d.customer_id = :customer)
               and (not :overdue or (d.status in ('HELD', 'DEPOSITED') and d.due_date < :today))
             order by d.due_date, d.number
            """
        ),
        {
            "plan": plan_id,
            "status": status,
            "type": paper_type,
            "customer": customer_id,
            "overdue": overdue_only,
            "today": today,
        },
    )
    return [_paper(row, today) for row in rows]


def _events(conn: Connection, paper_id: UUID) -> list[PaperEventOut]:
    rows = conn.execute(
        text(
            """
            select ev.from_status, ev.to_status, ev.event_date, ev.note, je.entry_no, ev.created_at
              from public.deferred_paper_events ev
              left join public.journal_entries je on je.id = ev.entry_id
             where ev.paper_id = :id order by ev.created_at
            """
        ),
        {"id": paper_id},
    ).mappings()
    return [PaperEventOut.model_validate(dict(r)) for r in rows]


def get_paper(conn: Connection, paper_id: UUID) -> PaperOut:
    row = conn.execute(text(_PAPERS + " where d.id = :id"), {"id": paper_id}).first()
    if row is None:
        raise not_found("deferred paper")
    return _paper(row, finance.tenant_info(conn).today, _events(conn, paper_id))


def _record_event(
    conn: Connection,
    paper_id: UUID,
    from_status: str | None,
    to_status: str,
    event_date: Any,
    note: str | None,
    entry_id: UUID | None = None,
) -> None:
    conn.execute(
        text(
            """
            insert into public.deferred_paper_events (tenant_id, paper_id, from_status, to_status, event_date, note,
                                                      entry_id, created_by)
            values (private.current_tenant_id(), :paper, :from_status, :to_status, :d, :note, :entry,
                    private.current_actor_id())
            """
        ),
        {
            "paper": paper_id,
            "from_status": from_status,
            "to_status": to_status,
            "d": event_date,
            "note": note,
            "entry": entry_id,
        },
    )


def create_paper(conn: Connection, payload: PaperIn) -> PaperOut:
    customers.active_customer(conn, payload.customer_id)
    if payload.installment_id is not None:
        owner = conn.execute(
            text(
                "select p.customer_id from public.installments i join public.installment_plans p on p.id = i.plan_id "
                "where i.id = :id"
            ),
            {"id": payload.installment_id},
        ).scalar_one_or_none()
        if owner != payload.customer_id:
            raise AppError("PAPER_INSTALLMENT_MISMATCH", "The installment belongs to another customer", status_code=422)
    paper_id = uuid4()
    try:
        conn.execute(
            text(
                """
                insert into public.deferred_papers
                  (id, tenant_id, paper_type, number, customer_id, installment_id, amount, issue_date, due_date,
                   storage_location, drawer_bank, drawer_branch, account_holder, notes)
                values (:id, private.current_tenant_id(), :paper_type, :number, :customer_id, :installment_id, :amount,
                        :issue_date, :due_date, :storage_location, :drawer_bank, :drawer_branch, :account_holder,
                        :notes)
                """
            ),
            {**payload.model_dump(), "id": paper_id},
        )
    except IntegrityError as exc:
        raise AppError(
            "PAPER_NUMBER_EXISTS", "A paper with this number is already registered", status_code=409
        ) from exc
    _record_event(conn, paper_id, None, "HELD", payload.issue_date or finance.tenant_info(conn).today, None)
    return get_paper(conn, paper_id)


# --- Actions ---------------------------------------------------------------------------------------------


def _paper_row(conn: Connection, paper_id: UUID, *, lock: bool) -> Any:
    if lock:
        conn.execute(text("select 1 from public.deferred_papers where id = :id for update"), {"id": paper_id})
    row = conn.execute(text(_PAPERS + " where d.id = :id"), {"id": paper_id}).first()
    if row is None:
        raise not_found("deferred paper")
    return row


def _bounce_drafts(
    conn: Connection, info: finance.TenantInfo, paper: Any, payload: PaperActionIn
) -> tuple[list[EntryDraft], finance.ActiveCashAccount | None]:
    """Rule 27 (+ P-07) when the cheque had already been collected; nothing otherwise (A-10)."""
    if paper.status != "COLLECTED":
        if payload.bank_charges:
            raise AppError("BANK_CHARGES_NOT_COLLECTED", "Bank charges apply to a collected cheque", status_code=422)
        return [], None
    receipt = conn.execute(
        text("select id, cash_account_id, amount from public.customer_receipts where id = :id and status = 'POSTED'"),
        {"id": paper.receipt_id},
    ).first()
    if receipt is None or receipt.cash_account_id is None:
        raise AppError("PAPER_RECEIPT_MISSING", "The receipt of this cheque cannot be found", status_code=409)
    bank = finance.active_cash_account(conn, receipt.cash_account_id)
    drafts = [
        rules.cheque_bounced(
            entry_date=payload.action_date,
            customer_id=paper.customer_id,
            amount=receipt.amount,
            bank=bank.ref,
            description=f"شيك مرتد رقم {paper.number} — {paper.customer_name}",
            source_id=paper.id,
        )
    ]
    if payload.bank_charges:
        drafts.append(
            rules.bounce_charges(
                entry_date=payload.action_date,
                amount=payload.bank_charges,
                bank=bank.ref,
                charge_customer_id=paper.customer_id if payload.charge_customer else None,
                description=f"مصاريف بنكية — شيك مرتد رقم {paper.number}",
                source_id=paper.id,
            )
        )
    return drafts, bank


def _check(conn: Connection, info: finance.TenantInfo, paper: Any, payload: PaperActionIn) -> str:
    finance.check_entry_date(info, payload.action_date)
    target = _NEXT[payload.action]
    allowed = conn.execute(
        text("select private.paper_transition_allowed(:type, :from_status, :to_status)"),
        {"type": paper.paper_type, "from_status": paper.status, "to_status": target},
    ).scalar_one()
    if not allowed:
        raise AppError(
            "PAPER_INVALID_TRANSITION",
            "The paper cannot move to this status",
            status_code=409,
            details={"from": paper.status, "to": target},
        )
    return target


def _collect_plan(
    conn: Connection, info: finance.TenantInfo, paper: Any, payload: PaperActionIn
) -> installments._ReceiptPlan:
    if paper.plan_id is None:
        raise AppError("PAPER_NOT_LINKED", "Link the paper to an installment before collecting it", status_code=422)
    if payload.cash_account_id is None:
        raise AppError("VALIDATION_ERROR", "Choose the account the money arrives in", status_code=422)
    return installments.plan_receipt(
        conn,
        info,
        paper.plan_id,
        receipt_date=payload.action_date,
        amount=paper.amount,
        received_in=finance.active_cash_account(conn, payload.cash_account_id),
        keep_excess_as_credit=False,
        description=f"تحصيل {'شيك' if paper.paper_type == 'PDC' else 'إيصال أمانة'} رقم {paper.number} — "
        f"{paper.customer_name}",
        first_installment=paper.installment_id,
    )


def preview_action(conn: Connection, paper_id: UUID, payload: PaperActionIn, *, with_lines: bool) -> Preview:
    info = finance.tenant_info(conn)
    paper = _paper_row(conn, paper_id, lock=False)
    target = _check(conn, info, paper, payload)
    amount_ar = format_money(paper.amount, info.currency, "ar")
    amount_en = format_money(paper.amount, info.currency, "en")
    label_ar = "الشيك" if paper.paper_type == "PDC" else "إيصال الأمانة"
    label_en = "cheque" if paper.paper_type == "PDC" else "promissory note"
    effects: list[PreviewEffect] = []
    lines = None
    if payload.action == "COLLECT":
        plan = _collect_plan(conn, info, paper, payload)
        finance.ensure_period_open(conn, payload.action_date)
        assert plan.cash is not None  # noqa: S101 - set for COLLECT
        summary_ar = (
            f"سيتم تحصيل {label_ar} رقم {paper.number} بقيمة {amount_ar} في «{plan.cash.name_ar}» "
            f"وخصمه من أقساط {paper.customer_name}."
        )
        summary_en = (
            f"The {label_en} no. {paper.number} for {amount_en} will be collected into “{plan.cash.name_en}” "
            f"and applied to {paper.customer_name}'s installments."
        )
        effects = [
            PreviewEffect(direction="IN", label_ar=plan.cash.name_ar, label_en=plan.cash.name_en, amount=paper.amount)
        ]
        lines = finance.preview_lines(conn, plan.draft) if with_lines else None
    elif payload.action == "BOUNCE":
        drafts, bank = _bounce_drafts(conn, info, paper, payload)
        if drafts and bank is not None:
            finance.ensure_period_open(conn, payload.action_date)
            summary_ar = (
                f"الشيك رقم {paper.number} ارتد بعد تحصيله: سيُخصم {amount_ar} من «{bank.name_ar}» "
                f"ويعود القسط مستحقاً على {paper.customer_name}."
            )
            summary_en = (
                f"Cheque no. {paper.number} bounced after collection: {amount_en} comes out of “{bank.name_en}” "
                f"and the installment is owed by {paper.customer_name} again."
            )
            total = sum((d.lines[-1].credit for d in drafts), ZERO)
            effects = [PreviewEffect(direction="OUT", label_ar=bank.name_ar, label_en=bank.name_en, amount=total)]
            if with_lines:
                lines = [line for d in drafts for line in finance.preview_lines(conn, d)]
        else:
            summary_ar = f"سيتم تسجيل ارتداد الشيك رقم {paper.number}؛ لم يكن قد حُصّل، فلا تتأثر الخزنة أو البنك."
            summary_en = (
                f"Cheque no. {paper.number} will be marked as bounced; it was not collected, so no money moves."
            )
    else:
        summary_ar = (
            f"سيتم تغيير حالة {label_ar} رقم {paper.number} إلى «{target}» "
            f"بتاريخ {ltr(payload.action_date.isoformat())}."
        )
        summary_en = f"The {label_en} no. {paper.number} will be marked {target} on {payload.action_date.isoformat()}."
    return Preview(summary_ar=summary_ar, summary_en=summary_en, effects=effects, lines=lines)


def act(conn: Connection, paper_id: UUID, payload: PaperActionIn) -> PostingResult[PaperOut]:
    info = finance.tenant_info(conn)
    paper = _paper_row(conn, paper_id, lock=True)
    target = _check(conn, info, paper, payload)
    entries: list[EntryRef] = []
    warnings: list[PostingWarning] = []
    receipt_id = paper.receipt_id
    if payload.action == "COLLECT":
        conn.execute(text("select 1 from public.installment_plans where id = :id for update"), {"id": paper.plan_id})
        plan = _collect_plan(conn, info, paper, payload)
        warnings = finance.check_cash(conn, info, plan.draft.cash_effects(), lock=True)
        receipt_id, posted = installments.post_receipt(
            conn,
            plan,
            receipt_date=payload.action_date,
            amount=paper.amount,
            source="PAPER",
            cash_account_id=payload.cash_account_id,
            deferred_paper_id=paper.id,
            notes=payload.note,
        )
        entries.append(EntryRef(id=posted.id, entry_no=posted.entry_no))
    elif payload.action == "BOUNCE":
        drafts, _ = _bounce_drafts(conn, info, paper, payload)
        for draft in drafts:
            warnings += finance.check_cash(conn, info, draft.cash_effects(), lock=True)
            posted = engine.post(conn, draft)
            entries.append(EntryRef(id=posted.id, entry_no=posted.entry_no))
        if drafts:
            # The receipt no longer counts: the installment reopens (rule 27).
            conn.execute(
                text("update public.customer_receipts set status = 'BOUNCED', bounce_entry_id = :entry where id = :id"),
                {"entry": entries[0].id, "id": paper.receipt_id},
            )
        notifications.notify_permission(
            conn,
            permission="installment.view",
            kind="CHEQUE_BOUNCED",
            params={"number": paper.number, "customer": paper.customer_name, "amount": f"{paper.amount:.2f}"},
            entity_type="DEFERRED_PAPER",
            entity_id=paper.id,
            dedupe_key=f"bounced:{paper.id}:{payload.action_date.isoformat()}",
        )
    try:
        conn.execute(
            text("update public.deferred_papers set status = :status, receipt_id = :receipt where id = :id"),
            {"status": target, "receipt": receipt_id, "id": paper_id},
        )
    except DBAPIError as exc:
        if getattr(exc.orig, "sqlstate", None) == "SR021":
            raise AppError("PAPER_INVALID_TRANSITION", "The paper cannot move to this status", status_code=409) from exc
        raise
    _record_event(
        conn, paper_id, paper.status, target, payload.action_date, payload.note, entries[0].id if entries else None
    )
    return PostingResult[PaperOut](document=get_paper(conn, paper_id), journal_entries=entries, warnings=warnings)


def return_held_papers(conn: Connection, plan_id: UUID, on_date: Any, note: str) -> None:
    """When a sale is cancelled its held papers go back to the customer."""
    for row in conn.execute(
        text(
            "select d.id, d.status from public.deferred_papers d join public.installments i on i.id = d.installment_id "
            "where i.plan_id = :plan and d.status = 'HELD'"
        ),
        {"plan": plan_id},
    ).fetchall():
        conn.execute(text("update public.deferred_papers set status = 'RETURNED' where id = :id"), {"id": row.id})
        _record_event(conn, row.id, row.status, "RETURNED", on_date, note)
