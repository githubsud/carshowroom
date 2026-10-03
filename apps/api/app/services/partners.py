"""Partners and capital (SPEC §4.2): records, effective-dated ownership,
partner money (rules 1-5, 28, 29), the partner statement and the summary.

Every amount here is derived from journal lines that carry the partner id
(BR-L11); nothing stores a partner balance.
"""

from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import Connection, text
from sqlalchemy.exc import DBAPIError

from app.core.crypto import FieldCipher, mask
from app.core.errors import AppError, not_found
from app.domain.finance import EntryRef, PostingResult, PostingWarning, Preview, PreviewEffect
from app.domain.ledger import ZERO, EntryDraft
from app.domain.money import format_money, ltr
from app.domain.partners import (
    Bucket,
    PartnerIn,
    PartnerOut,
    PartnerPosition,
    PartnerStatementOut,
    PartnerSummaryOut,
    PartnerSummaryRow,
    PartnerTransactionIn,
    PartnerTransactionOut,
    PartnerUpdate,
    ShareChangeIn,
    ShareOut,
    StatementLine,
)
from app.services import finance
from app.services.audit import record_event
from app.services.posting import engine, rules

# Partner subledger accounts and how they count towards the partner's net position.
_BUCKETS: dict[str, Bucket] = {
    "PARTNER_CAPITAL": "CAPITAL",
    "PARTNER_CURRENT": "CURRENT",
    "PARTNER_LOANS_RECEIVABLE": "LOAN_TO",
    "PARTNER_LOANS_PAYABLE": "LOAN_FROM",
}

_TXN_LABELS = {
    "CONTRIBUTION": ("مساهمة في رأس المال", "Capital contribution"),
    "CAPITAL_WITHDRAWAL": ("سحب من رأس المال", "Capital withdrawal"),
    "DRAWING": ("مسحوبات من الحصة", "Drawing from share"),
    "LOAN_TO_PARTNER": ("سلفة للشريك", "Loan to partner"),
    "LOAN_TO_PARTNER_REPAYMENT": ("سداد سلفة الشريك", "Partner loan repayment"),
    "LOAN_FROM_PARTNER": ("قرض من الشريك للمعرض", "Partner loan to the showroom"),
    "LOAN_FROM_PARTNER_REPAYMENT": ("سداد قرض الشريك", "Repayment to partner"),
}

# --- Partners --------------------------------------------------------------------------

_PARTNERS = """
    select p.id, p.name_ar, p.name_en, p.phone, p.national_id_last4, p.notes, p.archived_at is not null as archived,
           coalesce((select s.percentage from public.partner_share_history s
                      where s.partner_id = p.id and s.effective_from <= :on_date
                        and (s.effective_to is null or s.effective_to >= :on_date)), 0) as percentage
      from public.partners p
"""


def _partner_out(row: object) -> PartnerOut:
    data = dict(row._mapping)  # type: ignore[attr-defined]
    data["national_id_masked"] = mask(data.pop("national_id_last4"))
    return PartnerOut.model_validate(data)


def list_partners(conn: Connection, include_archived: bool = False) -> list[PartnerOut]:
    info = finance.tenant_info(conn)
    where = "" if include_archived else " where p.archived_at is null"
    rows = conn.execute(text(_PARTNERS + where + " order by percentage desc, p.name_ar"), {"on_date": info.today})
    return [_partner_out(row) for row in rows]


def get_partner(conn: Connection, partner_id: UUID) -> PartnerOut:
    info = finance.tenant_info(conn)
    row = conn.execute(text(_PARTNERS + " where p.id = :id"), {"id": partner_id, "on_date": info.today}).first()
    if row is None:
        raise not_found("partner")
    return _partner_out(row)


def _national_id_columns(cipher: FieldCipher, partner_id: UUID, national_id: str) -> dict[str, str]:
    return {
        "national_id_enc": cipher.encrypt(national_id, context=f"partner:{partner_id}"),
        "national_id_last4": national_id[-4:],
    }


def create_partner(conn: Connection, payload: PartnerIn, cipher: FieldCipher) -> PartnerOut:
    partner_id = uuid4()
    values: dict[str, object] = {
        "id": partner_id,
        "name_ar": payload.name_ar,
        "name_en": payload.name_en,
        "phone": payload.phone,
        "notes": payload.notes,
        "national_id_enc": None,
        "national_id_last4": None,
    }
    if payload.national_id:
        values.update(_national_id_columns(cipher, partner_id, payload.national_id))
    conn.execute(
        text(
            """
            insert into public.partners
              (id, tenant_id, name_ar, name_en, phone, notes, national_id_enc, national_id_last4)
            values (:id, private.current_tenant_id(), :name_ar, :name_en, :phone, :notes, :national_id_enc,
                    :national_id_last4)
            """
        ),
        values,
    )
    return get_partner(conn, partner_id)


def update_partner(conn: Connection, partner_id: UUID, changes: PartnerUpdate, cipher: FieldCipher) -> PartnerOut:
    current = get_partner(conn, partner_id)
    values: dict[str, object] = changes.model_dump(exclude_unset=True, exclude={"archived", "national_id"})
    if changes.national_id:
        values.update(_national_id_columns(cipher, partner_id, changes.national_id))
    if values:
        assignments = ", ".join(f"{column} = :{column}" for column in values)  # keys from a StrictModel
        conn.execute(
            text(f"update public.partners set {assignments} where id = :id"),  # noqa: S608
            {**values, "id": partner_id},
        )

    if changes.archived is True and not current.archived:
        # A partner leaves through a share change and a settlement first.
        position = positions(conn, [partner_id])[partner_id]
        open_balances = (position.capital, position.current, position.loans_to_partner, position.loans_from_partner)
        if current.percentage > 0 or any(amount != 0 for amount in open_balances):
            raise AppError(
                "PARTNER_NOT_SETTLED", "A partner with a share or an open balance cannot be archived", status_code=409
            )
        conn.execute(text("update public.partners set archived_at = now() where id = :id"), {"id": partner_id})
    elif changes.archived is False:
        conn.execute(text("update public.partners set archived_at = null where id = :id"), {"id": partner_id})
    return get_partner(conn, partner_id)


def reveal_national_id(conn: Connection, partner_id: UUID, cipher: FieldCipher, *, actor: UUID, tenant_id: UUID) -> str:
    token = conn.execute(
        text("select national_id_enc from public.partners where id = :id"), {"id": partner_id}
    ).scalar_one_or_none()
    if token is None:
        raise not_found("national id")
    value = cipher.decrypt(token, context=f"partner:{partner_id}")
    # Every unmasked view is recorded (SPEC §10).
    record_event(
        conn,
        tenant_id=tenant_id,
        actor=actor,
        action="NATIONAL_ID_VIEWED",
        entity_type="partners",
        entity_id=str(partner_id),
    )
    return value


# --- Ownership (effective-dated, append-only) -----------------------------------------------

_SHARES = """
    select s.partner_id, p.name_ar as partner_name_ar, p.name_en as partner_name_en, s.percentage,
           s.effective_from, s.effective_to
      from public.partner_share_history s
      join public.partners p on p.id = s.partner_id
"""


def shares_on(conn: Connection, on_date: date) -> list[ShareOut]:
    rows = conn.execute(
        text(
            _SHARES + " where s.effective_from <= :d and (s.effective_to is null or s.effective_to >= :d)"
            " order by s.percentage desc"
        ),
        {"d": on_date},
    ).mappings()
    return [ShareOut.model_validate(dict(row)) for row in rows]


def share_history(conn: Connection) -> list[ShareOut]:
    rows = conn.execute(text(_SHARES + " order by s.effective_from desc, s.percentage desc")).mappings()
    return [ShareOut.model_validate(dict(row)) for row in rows]


def change_shares(conn: Connection, payload: ShareChangeIn) -> list[ShareOut]:
    """Record a new ownership batch from `effective_from` (D-21): the open shares
    close the day before, the new ones open; the batch must total exactly 100%."""
    total = sum((share.percentage for share in payload.shares), Decimal(0))
    if total != Decimal(100):
        raise AppError(
            "SHARES_NOT_100", "Ownership must total exactly 100%", status_code=422, details={"total": f"{total:.4f}"}
        )

    known = set(
        conn.execute(
            text("select id from public.partners where archived_at is null and id = any(:ids)"),
            {"ids": [share.partner_id for share in payload.shares]},
        ).scalars()
    )
    unknown = [str(share.partner_id) for share in payload.shares if share.partner_id not in known]
    if unknown:
        raise AppError(
            "PARTNER_INVALID", "Unknown or archived partner", status_code=422, details={"partner_ids": unknown}
        )

    latest = conn.execute(text("select max(effective_from) from public.partner_share_history")).scalar_one()
    if latest is not None and payload.effective_from <= latest:
        # History is never rewritten: a change starts after the last one.
        raise AppError(
            "SHARE_DATE_INVALID",
            "A share change must start after the last change",
            status_code=422,
            details={"latest": latest.isoformat()},
        )

    batch = uuid4()
    conn.execute(
        text("update public.partner_share_history set effective_to = :day_before where effective_to is null"),
        {"day_before": payload.effective_from - timedelta(days=1)},
    )
    for share in payload.shares:
        conn.execute(
            text(
                """
                insert into public.partner_share_history
                  (tenant_id, partner_id, percentage, effective_from, change_batch_id)
                values (private.current_tenant_id(), :partner_id, :percentage, :effective_from, :batch)
                """
            ),
            {
                "partner_id": share.partner_id,
                "percentage": share.percentage,
                "effective_from": payload.effective_from,
                "batch": batch,
            },
        )
    try:
        conn.execute(text("set constraints all immediate"))
        conn.execute(text("set constraints all deferred"))
    except DBAPIError as exc:  # the database's own 100% check (SR010)
        if getattr(exc.orig, "sqlstate", None) == "SR010":
            raise AppError(
                "SHARES_NOT_100", "Ownership must total exactly 100% on every date", status_code=422
            ) from exc
        raise
    return shares_on(conn, payload.effective_from)


# --- Positions ------------------------------------------------------------------------------------


def positions(conn: Connection, partner_ids: list[UUID], as_of: date | None = None) -> dict[UUID, PartnerPosition]:
    rows = conn.execute(
        text(
            """
            select l.partner_id, a.system_key, sum(l.credit - l.debit) as net_credit
              from public.journal_lines l
              join public.ledger_accounts a on a.id = l.ledger_account_id
             where l.partner_id = any(:ids) and a.system_key = any(:keys)
               and (cast(:as_of as date) is null or l.entry_date <= :as_of)
             group by l.partner_id, a.system_key
            """
        ),
        {"ids": partner_ids, "keys": list(_BUCKETS), "as_of": as_of},
    )
    sums: dict[UUID, dict[str, Decimal]] = {pid: {} for pid in partner_ids}
    for row in rows:
        sums[row.partner_id][row.system_key] = Decimal(row.net_credit)
    return {pid: _position(values) for pid, values in sums.items()}


def _position(net_credit: dict[str, Decimal]) -> PartnerPosition:
    capital = net_credit.get("PARTNER_CAPITAL", ZERO)
    current = net_credit.get("PARTNER_CURRENT", ZERO)
    loans_to = -net_credit.get("PARTNER_LOANS_RECEIVABLE", ZERO)
    loans_from = net_credit.get("PARTNER_LOANS_PAYABLE", ZERO)
    return PartnerPosition(
        capital=capital,
        current=current,
        loans_to_partner=loans_to,
        loans_from_partner=loans_from,
        net=capital + current - loans_to + loans_from,
    )


# --- Partner transactions (rules 1-5, 28, 29) -----------------------------------------------------


def _plan_transaction(
    conn: Connection, info: finance.TenantInfo, partner: PartnerOut, payload: PartnerTransactionIn
) -> tuple[EntryDraft, finance.ActiveCashAccount, list[PostingWarning]]:
    finance.check_entry_date(info, payload.txn_date)
    if partner.archived:
        raise AppError("PARTNER_INVALID", "The partner is archived", status_code=422)
    cash = finance.active_cash_account(conn, payload.cash_account_id)
    position = positions(conn, [partner.id])[partner.id]
    warnings: list[PostingWarning] = []
    amount = payload.amount

    # A repayment cannot exceed what is owed (by analogy with business rule 3; D-63).
    if payload.type == "LOAN_TO_PARTNER_REPAYMENT" and amount > position.loans_to_partner:
        raise AppError(
            "REPAYMENT_EXCEEDS_LOAN",
            "The repayment is more than the partner owes",
            status_code=422,
            details={"outstanding": f"{position.loans_to_partner:.2f}"},
        )
    if payload.type == "LOAN_FROM_PARTNER_REPAYMENT" and amount > position.loans_from_partner:
        raise AppError(
            "REPAYMENT_EXCEEDS_LOAN",
            "The repayment is more than the showroom owes the partner",
            status_code=422,
            details={"outstanding": f"{position.loans_from_partner:.2f}"},
        )
    # Drawings beyond the current account are allowed but flagged (SPEC §4.17, Q-17).
    if payload.type == "DRAWING" and position.current - amount < 0:
        warnings.append(
            PostingWarning(
                code="DRAWING_EXCEEDS_BALANCE",
                details={
                    "name_ar": partner.name_ar,
                    "name_en": partner.name_en or partner.name_ar,
                    "balance_after": f"{position.current - amount:.2f}",
                },
            )
        )
    if payload.type == "CAPITAL_WITHDRAWAL" and position.capital - amount < 0:
        warnings.append(
            PostingWarning(
                code="CAPITAL_NEGATIVE",
                details={
                    "name_ar": partner.name_ar,
                    "name_en": partner.name_en or partner.name_ar,
                    "balance_after": f"{position.capital - amount:.2f}",
                },
            )
        )

    label_ar, _ = _TXN_LABELS[payload.type]
    draft = rules.partner_transaction(
        kind=payload.type,
        entry_date=payload.txn_date,
        amount=amount,
        partner_id=partner.id,
        cash=cash.ref,
        description=payload.notes or f"{label_ar} — {partner.name_ar}",
        source_id=None,
    )
    return draft, cash, warnings


def preview_transaction(
    conn: Connection, partner_id: UUID, payload: PartnerTransactionIn, *, with_lines: bool
) -> Preview:
    info = finance.tenant_info(conn)
    partner = get_partner(conn, partner_id)
    draft, cash, warnings = _plan_transaction(conn, info, partner, payload)
    finance.ensure_period_open(conn, payload.txn_date)
    warnings += finance.check_cash(conn, info, draft.cash_effects(), lock=False)

    amount_ar = format_money(payload.amount, info.currency, "ar")
    amount_en = format_money(payload.amount, info.currency, "en")
    label_ar, label_en = _TXN_LABELS[payload.type]
    name_en = partner.name_en or partner.name_ar
    money_in = rules.PARTNER_TRANSACTION_RULES[payload.type][1]
    if money_in:
        summary_ar = f"سيتم إضافة {amount_ar} إلى «{cash.name_ar}» وتسجيلها كـ{label_ar} للشريك {partner.name_ar}"
        summary_en = f"{amount_en} will be added to “{cash.name_en}” as a {label_en.lower()} by partner {name_en}"
    else:
        summary_ar = f"سيتم خصم {amount_ar} من «{cash.name_ar}» وتسجيلها كـ{label_ar} للشريك {partner.name_ar}"
        summary_en = f"{amount_en} will be paid from “{cash.name_en}” as a {label_en.lower()} for partner {name_en}"
    return Preview(
        summary_ar=f"{summary_ar} بتاريخ {ltr(payload.txn_date.isoformat())}.",
        summary_en=f"{summary_en} on {payload.txn_date.isoformat()}.",
        effects=[
            PreviewEffect(
                direction="IN" if money_in else "OUT",
                label_ar=cash.name_ar,
                label_en=cash.name_en,
                amount=payload.amount,
            )
        ],
        warnings=warnings,
        lines=finance.preview_lines(conn, draft) if with_lines else None,
    )


def record_transaction(
    conn: Connection, partner_id: UUID, payload: PartnerTransactionIn
) -> PostingResult[PartnerTransactionOut]:
    info = finance.tenant_info(conn)
    # Lock the partner row: two concurrent repayments cannot both pass the "owed" check.
    conn.execute(text("select 1 from public.partners where id = :id for update"), {"id": partner_id})
    partner = get_partner(conn, partner_id)
    draft, _, warnings = _plan_transaction(conn, info, partner, payload)
    warnings += finance.check_cash(conn, info, draft.cash_effects(), lock=True)
    document_id = uuid4()
    posted = engine.post(conn, replace(draft, source_id=document_id))
    conn.execute(
        text(
            """
            insert into public.partner_transactions
              (id, tenant_id, partner_id, type, txn_date, amount, cash_account_id, notes, journal_entry_id)
            values
              (:id, private.current_tenant_id(), :partner_id, :type, :txn_date, :amount, :cash_account_id, :notes,
               :journal_entry_id)
            """
        ),
        {**payload.model_dump(), "id": document_id, "partner_id": partner_id, "journal_entry_id": posted.id},
    )
    return PostingResult[PartnerTransactionOut](
        document=get_transaction(conn, document_id),
        journal_entries=[EntryRef(id=posted.id, entry_no=posted.entry_no)],
        warnings=warnings,
    )


_TRANSACTIONS = """
    select t.id, t.partner_id, p.name_ar as partner_name_ar, t.type, t.txn_date, t.amount, t.cash_account_id,
           ca.name_ar as cash_account_name_ar, t.notes, t.status, je.entry_no, rje.entry_no as reversal_entry_no
      from public.partner_transactions t
      join public.partners p on p.id = t.partner_id
      join public.cash_accounts ca on ca.id = t.cash_account_id
      join public.journal_entries je on je.id = t.journal_entry_id
      left join public.journal_entries rje on rje.id = t.reversal_entry_id
"""


def get_transaction(conn: Connection, transaction_id: UUID) -> PartnerTransactionOut:
    row = conn.execute(text(_TRANSACTIONS + " where t.id = :id"), {"id": transaction_id}).mappings().first()
    if row is None:
        raise not_found("partner transaction")
    return PartnerTransactionOut.model_validate(dict(row))


def list_transactions(conn: Connection, partner_id: UUID) -> list[PartnerTransactionOut]:
    rows = conn.execute(
        text(_TRANSACTIONS + " where t.partner_id = :id order by t.txn_date desc, je.entry_no desc"),
        {"id": partner_id},
    ).mappings()
    return [PartnerTransactionOut.model_validate(dict(row)) for row in rows]


# --- Statement (كشف حساب شريك) -----------------------------------------------------------------------

_STATEMENT_LINES = text(
    """
    select e.entry_date, e.entry_no, e.description, e.source_type, a.system_key, l.debit, l.credit,
           e.reversal_of_id is not null as is_reversal, e.reversed_by_id is not null as reversed
      from public.journal_lines l
      join public.journal_entries e on e.id = l.journal_entry_id
      join public.ledger_accounts a on a.id = l.ledger_account_id
     where l.partner_id = :id and a.system_key = any(:keys)
       and l.entry_date between :date_from and :date_to
     order by l.entry_date, e.entry_no, l.line_no
    """
)


def statement(conn: Connection, partner_id: UUID, date_from: date, date_to: date) -> PartnerStatementOut:
    if date_from > date_to:
        raise AppError("DATE_RANGE_INVALID", "The start date is after the end date", status_code=422)
    partner = get_partner(conn, partner_id)
    info = finance.tenant_info(conn)
    opening = positions(conn, [partner_id], as_of=date_from - timedelta(days=1))[partner_id]
    running = Decimal(opening.net)
    lines = []
    for row in conn.execute(
        _STATEMENT_LINES, {"id": partner_id, "keys": list(_BUCKETS), "date_from": date_from, "date_to": date_to}
    ):
        running += row.credit - row.debit
        lines.append(
            StatementLine(
                entry_date=row.entry_date,
                entry_no=row.entry_no,
                description=row.description,
                source_type=row.source_type,
                bucket=_BUCKETS[row.system_key],
                amount_in=row.credit,
                amount_out=row.debit,
                running_net=running,
                is_reversal=row.is_reversal,
                reversed=row.reversed,
            )
        )
    closing = positions(conn, [partner_id], as_of=date_to)[partner_id]
    return PartnerStatementOut(
        partner=partner,
        date_from=date_from,
        date_to=date_to,
        currency_code=info.currency,
        opening=opening,
        closing=closing,
        lines=lines,
    )


# --- Summary (one row per partner, SPEC §4.2) ----------------------------------------------------------


def summary(conn: Connection, as_of: date | None) -> PartnerSummaryOut:
    info = finance.tenant_info(conn)
    on_date = as_of or info.today
    partners = conn.execute(text(_PARTNERS + " order by percentage desc, p.name_ar"), {"on_date": on_date}).fetchall()
    ids = [row.id for row in partners]
    position_by_partner = positions(conn, ids, as_of=on_date)
    flows = {
        row.partner_id: row
        for row in conn.execute(
            text(
                """
                select l.partner_id,
                       coalesce(sum(l.credit - l.debit)
                                  filter (where e.source_type in ('PROFIT_DISTRIBUTION', 'PROFIT_ALLOCATION')), 0)
                         as allocated_profit,
                       coalesce(sum(l.debit - l.credit) filter (where e.source_type = 'PARTNER_DRAWING'), 0)
                         as drawings
                  from public.journal_lines l
                  join public.journal_entries e on e.id = l.journal_entry_id
                  join public.ledger_accounts a on a.id = l.ledger_account_id
                 where l.partner_id = any(:ids) and a.system_key = 'PARTNER_CURRENT' and l.entry_date <= :on_date
                 group by l.partner_id
                """
            ),
            {"ids": ids, "on_date": on_date},
        )
    }

    rows: list[PartnerSummaryRow] = []
    for partner in partners:
        position = position_by_partner[partner.id]
        flow = flows.get(partner.id)
        has_anything = partner.percentage > 0 or position.net != 0 or position.loans_to_partner != 0
        if partner.archived and not has_anything:
            continue
        rows.append(
            PartnerSummaryRow(
                partner_id=partner.id,
                name_ar=partner.name_ar,
                name_en=partner.name_en,
                percentage=partner.percentage,
                capital=position.capital,
                allocated_profit=Decimal(flow.allocated_profit) if flow else ZERO,
                drawings=Decimal(flow.drawings) if flow else ZERO,
                current=position.current,
                loans_to_partner=position.loans_to_partner,
                loans_from_partner=position.loans_from_partner,
                net=position.net,
            )
        )

    def total(field: str) -> Decimal:
        return sum((Decimal(getattr(row, field)) for row in rows), ZERO)

    totals = PartnerSummaryRow(
        partner_id=UUID(int=0),
        name_ar="الإجمالي",
        name_en="Total",
        percentage=total("percentage"),
        capital=total("capital"),
        allocated_profit=total("allocated_profit"),
        drawings=total("drawings"),
        current=total("current"),
        loans_to_partner=total("loans_to_partner"),
        loans_from_partner=total("loans_from_partner"),
        net=total("net"),
    )
    return PartnerSummaryOut(as_of=on_date, currency_code=info.currency, rows=rows, totals=totals)
