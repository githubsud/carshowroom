"""Period close and profit distribution (SPEC §4.9; rules 22, 23; D-40).

A distribution closes a date range: rule 23 moves every income and expense
balance of the range into retained earnings (a closing entry, D-29), then
rule 22 credits each partner's current account by the tenant's options:

* PERIODIC: the whole net profit; PER_CAR: what the sales of the range did not
  already allocate (P-10, netted against 3310 first).
* DAY_WEIGHTED or SUB_PERIOD_PROFIT pro-rata when shares change mid-range.
* LARGEST_REMAINDER or LARGEST_SHARE for the rounding cents.
* A loss is charged to the partners (P-09) or carried forward in 3300.

The preview runs exactly the plan that posting runs. Ranges never overlap and
never leave a gap; once distributed, nothing but closing entries may be dated
inside a range (D-101). Only the latest distribution can be reversed.
"""

from dataclasses import dataclass, replace
from datetime import date, timedelta
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID, uuid4

from sqlalchemy import Connection, text
from sqlalchemy.exc import IntegrityError

from app.core.errors import AppError, not_found
from app.domain.distribution import (
    DistributionError,
    DistributionIn,
    DistributionLineOut,
    DistributionOut,
    DistributionPlanOut,
    Segment,
    ShareRow,
    allocate,
    day_weights,
    round_shares,
    segments,
    sub_period_shares,
)
from app.domain.finance import EntryRef, PostingResult
from app.domain.ledger import ZERO, Account, EntryDraft, Line
from app.domain.money import format_money, ltr
from app.services import finance, partners
from app.services.posting import engine, rules

_SETTINGS = text("select profit_policy, prorata_method, rounding_remainder, loss_handling from public.tenant_settings")


def _money(amount: Decimal, info: finance.TenantInfo, language: Literal["ar", "en"]) -> str:
    return format_money(amount, info.currency, language)


def _app_error(exc: DistributionError) -> AppError:
    return AppError(exc.code, str(exc), status_code=422)


def _history(conn: Connection) -> list[ShareRow]:
    rows = conn.execute(
        text("select partner_id, percentage, effective_from, effective_to from public.partner_share_history")
    )
    return [ShareRow(r.partner_id, Decimal(r.percentage), r.effective_from, r.effective_to) for r in rows]


# --- Balances -----------------------------------------------------------------------------------------------

_PNL_BALANCES = text(
    """
    select l.ledger_account_id, a.type, l.cash_account_id, l.partner_id, l.customer_id, l.vehicle_id,
           l.consignor_id, l.external_showroom_id, l.supplier_id,
           sum(l.debit) as debit, sum(l.credit) as credit
      from public.journal_lines l
      join public.journal_entries e on e.id = l.journal_entry_id
      join public.ledger_accounts a on a.id = l.ledger_account_id
     where a.type in ('INCOME', 'EXPENSE') and not e.is_closing
       and l.entry_date between :date_from and :date_to
     group by l.ledger_account_id, a.type, l.cash_account_id, l.partner_id, l.customer_id, l.vehicle_id,
              l.consignor_id, l.external_showroom_id, l.supplier_id
     order by min(a.code), l.ledger_account_id
    """
)

_NET_BY_DAY = text(
    """
    select l.entry_date, sum(l.credit - l.debit) as net
      from public.journal_lines l
      join public.journal_entries e on e.id = l.journal_entry_id
      join public.ledger_accounts a on a.id = l.ledger_account_id
     where a.type in ('INCOME', 'EXPENSE') and not e.is_closing
       and l.entry_date between :date_from and :date_to
     group by l.entry_date
    """
)

_ACCOUNT_BALANCE = text(
    """
    select coalesce(sum(l.debit - l.credit), 0)
      from public.journal_lines l join public.ledger_accounts a on a.id = l.ledger_account_id
     where a.system_key = :key and l.entry_date <= :until
       and (cast(:since as date) is null or l.entry_date >= :since)
    """
)


def _balance(conn: Connection, key: str, until: date, since: date | None = None) -> Decimal:
    return Decimal(conn.execute(_ACCOUNT_BALANCE, {"key": key, "until": until, "since": since}).scalar_one())


@dataclass(frozen=True)
class _Plan:
    out: DistributionPlanOut
    closing: EntryDraft | None
    netting: EntryDraft | None
    distribution: EntryDraft | None
    weights: dict[UUID, Decimal]


def _check_range(conn: Connection, info: finance.TenantInfo, period_from: date, period_to: date) -> None:
    if period_to < period_from:
        raise AppError("DATE_RANGE_INVALID", "The period ends before it starts", status_code=422)
    if period_to > info.today:
        raise AppError("DATE_IN_FUTURE", "A period can be closed only once it has ended", status_code=422)
    last = conn.execute(
        text("select max(period_to) from public.profit_distributions where status = 'POSTED'")
    ).scalar_one()
    if last is not None and period_from <= last:
        raise AppError(
            "DISTRIBUTION_PERIOD_OVERLAP",
            "This period has already been distributed",
            status_code=409,
            details={"distributed_until": last.isoformat()},
        )
    # No gap (D-101): nothing earlier may stay undistributed.
    since = last + timedelta(days=1) if last is not None else None
    first = conn.execute(
        text(
            """
            select min(l.entry_date)
              from public.journal_lines l
              join public.journal_entries e on e.id = l.journal_entry_id
              join public.ledger_accounts a on a.id = l.ledger_account_id
             where a.type in ('INCOME', 'EXPENSE') and not e.is_closing
               and (cast(:since as date) is null or l.entry_date >= :since)
            """
        ),
        {"since": since},
    ).scalar_one()
    expected = since if since is not None else first
    if expected is not None and period_from > expected:
        raise AppError(
            "DISTRIBUTION_PERIOD_GAP",
            "The period must start where the last distribution ended (or at the first activity)",
            status_code=422,
            details={"period_from": expected.isoformat()},
        )


def _segment_amounts(
    conn: Connection, parts: list[Segment], period_from: date, period_to: date, per_car: bool
) -> list[Decimal]:
    """Each stretch's own net profit, less what its sales already allocated (P-10)."""
    by_day = {
        row.entry_date: Decimal(row.net)
        for row in conn.execute(_NET_BY_DAY, {"date_from": period_from, "date_to": period_to})
    }
    amounts = []
    for part in parts:
        net = sum((v for d, v in by_day.items() if part.start <= d <= part.end), ZERO)
        if per_car:
            net -= _balance(conn, "PROFIT_ALLOCATED_IN_ADVANCE", part.end, part.start)
        amounts.append(net)
    return amounts


def _plan(conn: Connection, payload: DistributionIn) -> _Plan:
    info = finance.tenant_info(conn)
    _check_range(conn, info, payload.period_from, payload.period_to)
    settings = conn.execute(_SETTINGS).mappings().one()
    per_car = settings["profit_policy"] == "PER_CAR"

    rows = list(conn.execute(_PNL_BALANCES, {"date_from": payload.period_from, "date_to": payload.period_to}))
    balances = [
        Line(
            account=Account.by_id(r.ledger_account_id),
            debit=Decimal(r.debit) - Decimal(r.credit) if r.debit > r.credit else ZERO,
            credit=Decimal(r.credit) - Decimal(r.debit) if r.credit > r.debit else ZERO,
            cash_account_id=r.cash_account_id,
            partner_id=r.partner_id,
            customer_id=r.customer_id,
            vehicle_id=r.vehicle_id,
            consignor_id=r.consignor_id,
            external_showroom_id=r.external_showroom_id,
            supplier_id=r.supplier_id,
        )
        for r in rows
    ]
    revenue = sum((Decimal(r.credit) - Decimal(r.debit) for r in rows if r.type == "INCOME"), ZERO)
    expenses = sum((Decimal(r.debit) - Decimal(r.credit) for r in rows if r.type == "EXPENSE"), ZERO)
    net = revenue - expenses
    label = f"{ltr(payload.period_from.isoformat())} — {ltr(payload.period_to.isoformat())}"
    closing = None
    if any(line.debit != line.credit for line in balances):
        closing = rules.period_close(
            entry_date=payload.period_to, balances=balances, description=f"إقفال الفترة {label}", source_id=None
        )

    advance = _balance(conn, "PROFIT_ALLOCATED_IN_ADVANCE", payload.period_to) if per_car else ZERO
    netting = (
        rules.advance_netting(
            entry_date=payload.period_to, amount=advance, description=f"مقاصة أرباح السيارات {label}", source_id=None
        )
        if advance != 0
        else None
    )
    carried_in = ZERO
    if settings["loss_handling"] == "CARRY_FORWARD":
        # 3300 holds a credit balance; a debit (negative here) is a loss carried forward.
        carried_in = min(ZERO, -_balance(conn, "RETAINED_EARNINGS", payload.period_to))
    distributable = net - advance + carried_in

    try:
        parts = segments(_history(conn), payload.period_from, payload.period_to)
    except DistributionError as exc:
        raise _app_error(exc) from exc
    weights = day_weights(parts)
    method = settings["rounding_remainder"]
    carry_loss = settings["loss_handling"] == "CARRY_FORWARD" and distributable < 0
    to_partners = ZERO if carry_loss else distributable
    shares: dict[UUID, Decimal] = dict.fromkeys(weights, ZERO)
    if to_partners != 0:
        if settings["prorata_method"] == "SUB_PERIOD_PROFIT":
            amounts = _segment_amounts(conn, parts, payload.period_from, payload.period_to, per_car)
            amounts[0] += carried_in  # a loss carried in belongs to the start of the range
            shares = round_shares(sub_period_shares(parts, amounts), to_partners, weights, method)
        else:
            shares = allocate(to_partners, weights, method)
    distribution = None
    if to_partners != 0:
        distribution = rules.profit_distribution(
            entry_date=payload.period_to,
            shares=sorted(shares.items(), key=lambda item: -weights[item[0]]),
            description=f"توزيع أرباح الفترة {label}",
            source_id=None,
        )

    names = {s.partner_id: (s.partner_name_ar, s.partner_name_en) for s in partners.share_history(conn)}
    lines = [
        DistributionLineOut(
            partner_id=partner,
            partner_name_ar=names.get(partner, ("", None))[0],
            partner_name_en=names.get(partner, ("", None))[1],
            weight_pct=weights[partner].quantize(Decimal("0.00000001")),
            amount=shares.get(partner, ZERO),
        )
        for partner in sorted(weights, key=lambda p: -weights[p])
    ]
    carried_out = distributable if carry_loss else ZERO
    out = DistributionPlanOut(
        period_from=payload.period_from,
        period_to=payload.period_to,
        profit_policy=settings["profit_policy"],
        prorata_method=settings["prorata_method"],
        rounding_remainder=method,
        loss_handling=settings["loss_handling"],
        revenue=revenue,
        expenses=expenses,
        net_profit=net,
        allocated_in_advance=advance,
        carried_in=carried_in,
        distributed=to_partners,
        carried_out=carried_out,
        lines=lines,
        summary_ar=_summary(info, net, advance, carried_in, to_partners, carried_out, lines, "ar"),
        summary_en=_summary(info, net, advance, carried_in, to_partners, carried_out, lines, "en"),
    )
    return _Plan(out=out, closing=closing, netting=netting, distribution=distribution, weights=weights)


def _summary(
    info: finance.TenantInfo,
    net: Decimal,
    advance: Decimal,
    carried_in: Decimal,
    distributed: Decimal,
    carried_out: Decimal,
    lines: list[DistributionLineOut],
    language: Literal["ar", "en"],
) -> str:
    def m(value: Decimal) -> str:
        return _money(value, info, language)

    if language == "ar":
        head = f"صافي ربح الفترة {m(net)}" if net >= 0 else f"صافي خسارة الفترة {m(-net)}"
        parts = [head]
        if advance:
            parts.append(f"منه {m(advance)} وُزّع مع بيع كل سيارة")
        if carried_in:
            parts.append(f"وخسارة مرحّلة {m(-carried_in)}")
        if distributed:
            each = "، ".join(f"{line.partner_name_ar} {m(line.amount)}" for line in lines if line.amount)
            parts.append(f"يُوزَّع {m(distributed)} على حسابات الشركاء الجارية: {each}")
        if carried_out:
            parts.append(f"تُرحَّل خسارة {m(-carried_out)} للفترة القادمة")
        return "؛ ".join(parts) + ". الصرف الفعلي للشركاء يكون كمسحوبات منفصلة."
    head = f"Net profit for the period {m(net)}" if net >= 0 else f"Net loss for the period {m(-net)}"
    parts = [head]
    if advance:
        parts.append(f"{m(advance)} of it was already allocated with each car sold")
    if carried_in:
        parts.append(f"a loss of {m(-carried_in)} carried in")
    if distributed:
        each = ", ".join(
            f"{line.partner_name_en or line.partner_name_ar} {m(line.amount)}" for line in lines if line.amount
        )
        parts.append(f"{m(distributed)} goes to the partners' current accounts: {each}")
    if carried_out:
        parts.append(f"a loss of {m(-carried_out)} is carried forward")
    return "; ".join(parts) + ". Paying partners out is a separate drawing."


def preview(conn: Connection, payload: DistributionIn) -> DistributionPlanOut:
    plan = _plan(conn, payload)
    finance.ensure_period_open(conn, payload.period_to)
    return plan.out


def post(conn: Connection, payload: DistributionIn, *, user_id: UUID) -> PostingResult[DistributionOut]:
    conn.execute(text("select pg_advisory_xact_lock(hashtext('distribution:' || private.current_tenant_id()))"))
    plan = _plan(conn, payload)
    distribution_id = uuid4()
    entries: list[EntryRef] = []
    posted: dict[str, UUID | None] = {}
    for key, draft in (("closing", plan.closing), ("netting", plan.netting), ("distribution", plan.distribution)):
        if draft is None:
            posted[key] = None
            continue
        entry = engine.post(conn, replace(draft, source_id=distribution_id))
        posted[key] = entry.id
        entries.append(EntryRef(id=entry.id, entry_no=entry.entry_no))
    out = plan.out
    try:
        conn.execute(
            text(
                """
                insert into public.profit_distributions
                  (id, tenant_id, period_from, period_to, profit_policy, prorata_method, rounding_remainder,
                   loss_handling, net_profit, allocated_in_advance, carried_in, distributed,
                   closing_journal_entry_id, netting_journal_entry_id, distribution_journal_entry_id, notes)
                values (:id, private.current_tenant_id(), :period_from, :period_to, :profit_policy, :prorata_method,
                        :rounding_remainder, :loss_handling, :net_profit, :allocated_in_advance, :carried_in,
                        :distributed, :closing, :netting, :distribution, :notes)
                """
            ),
            {
                **out.model_dump(
                    include={
                        "period_from",
                        "period_to",
                        "profit_policy",
                        "prorata_method",
                        "rounding_remainder",
                        "loss_handling",
                        "net_profit",
                        "allocated_in_advance",
                        "carried_in",
                        "distributed",
                    }
                ),
                "id": distribution_id,
                "closing": posted["closing"],
                "netting": posted["netting"],
                "distribution": posted["distribution"],
                "notes": payload.notes,
            },
        )
    except IntegrityError as exc:
        if "profit_distributions_no_overlap" in str(exc.orig):
            raise AppError(
                "DISTRIBUTION_PERIOD_OVERLAP", "This period has already been distributed", status_code=409
            ) from exc
        raise
    for line in out.lines:
        conn.execute(
            text(
                """
                insert into public.profit_distribution_lines
                  (tenant_id, distribution_id, partner_id, weight_pct, amount)
                values (private.current_tenant_id(), :distribution, :partner, :weight, :amount)
                """
            ),
            {
                "distribution": distribution_id,
                "partner": line.partner_id,
                "weight": line.weight_pct,
                "amount": line.amount,
            },
        )
    return PostingResult[DistributionOut](document=get(conn, distribution_id), journal_entries=entries)


_DISTRIBUTIONS = """
    select d.*, ce.entry_no as closing_entry_no, de.entry_no as distribution_entry_no
      from public.profit_distributions d
      left join public.journal_entries ce on ce.id = d.closing_journal_entry_id
      left join public.journal_entries de on de.id = d.distribution_journal_entry_id
"""


def _out(conn: Connection, row: Any) -> DistributionOut:
    info = finance.tenant_info(conn)
    lines = [
        DistributionLineOut.model_validate(dict(r))
        for r in conn.execute(
            text(
                """
                select l.partner_id, p.name_ar as partner_name_ar, p.name_en as partner_name_en, l.weight_pct, l.amount
                  from public.profit_distribution_lines l join public.partners p on p.id = l.partner_id
                 where l.distribution_id = :id order by l.weight_pct desc, p.name_ar
                """
            ),
            {"id": row["id"]},
        ).mappings()
    ]
    net, advance, carried_in = (
        Decimal(row["net_profit"]),
        Decimal(row["allocated_in_advance"]),
        Decimal(row["carried_in"]),
    )
    distributed = Decimal(row["distributed"])
    carried_out = net - advance + carried_in - distributed
    revenue_row = conn.execute(
        text(
            """
            select coalesce(sum(l.credit - l.debit) filter (where a.type = 'INCOME'), 0) as revenue,
                   coalesce(sum(l.debit - l.credit) filter (where a.type = 'EXPENSE'), 0) as expenses
              from public.journal_lines l
              join public.journal_entries e on e.id = l.journal_entry_id
              join public.ledger_accounts a on a.id = l.ledger_account_id
             where not e.is_closing and l.entry_date between :f and :t
            """
        ),
        {"f": row["period_from"], "t": row["period_to"]},
    ).one()
    return DistributionOut(
        id=row["id"],
        status=row["status"],
        period_from=row["period_from"],
        period_to=row["period_to"],
        profit_policy=row["profit_policy"],
        prorata_method=row["prorata_method"],
        rounding_remainder=row["rounding_remainder"],
        loss_handling=row["loss_handling"],
        revenue=Decimal(revenue_row.revenue),
        expenses=Decimal(revenue_row.expenses),
        net_profit=net,
        allocated_in_advance=advance,
        carried_in=carried_in,
        distributed=distributed,
        carried_out=carried_out,
        lines=lines,
        summary_ar=_summary(info, net, advance, carried_in, distributed, carried_out, lines, "ar"),
        summary_en=_summary(info, net, advance, carried_in, distributed, carried_out, lines, "en"),
        closing_entry_no=row["closing_entry_no"],
        distribution_entry_no=row["distribution_entry_no"],
        created_at=row["created_at"],
        reversal_reason=row["reversal_reason"],
        notes=row["notes"],
    )


def get(conn: Connection, distribution_id: UUID) -> DistributionOut:
    row = conn.execute(text(_DISTRIBUTIONS + " where d.id = :id"), {"id": distribution_id}).mappings().first()
    if row is None:
        raise not_found("distribution")
    return _out(conn, row)


def list_distributions(conn: Connection) -> list[DistributionOut]:
    rows = conn.execute(text(_DISTRIBUTIONS + " order by d.period_to desc, d.created_at desc")).mappings()
    return [_out(conn, row) for row in rows]


def reverse(conn: Connection, distribution_id: UUID, reason: str, *, user_id: UUID) -> DistributionOut:
    """Undo the latest distribution: its entries are mirrored on their own date, so
    the range is exactly as it was before closing (only the latest, D-102)."""
    conn.execute(text("select pg_advisory_xact_lock(hashtext('distribution:' || private.current_tenant_id()))"))
    current = get(conn, distribution_id)
    if current.status != "POSTED":
        raise AppError("DISTRIBUTION_REVERSED", "This distribution has already been reversed", status_code=409)
    later = conn.execute(
        text("select 1 from public.profit_distributions where status = 'POSTED' and period_to > :t"),
        {"t": current.period_to},
    ).first()
    if later is not None:
        raise AppError("DISTRIBUTION_NOT_LATEST", "Reverse the later distributions first", status_code=409)
    row = conn.execute(
        text(
            "select closing_journal_entry_id, netting_journal_entry_id, distribution_journal_entry_id "
            "from public.profit_distributions where id = :id"
        ),
        {"id": distribution_id},
    ).one()
    for entry_id in (row.distribution_journal_entry_id, row.netting_journal_entry_id, row.closing_journal_entry_id):
        if entry_id is not None:
            engine.reverse(conn, entry_id, reason, current.period_to)
    conn.execute(
        text(
            "update public.profit_distributions set status = 'REVERSED', reversed_at = now(), reversed_by = :user, "
            "reversal_reason = :reason where id = :id"
        ),
        {"user": user_id, "reason": reason, "id": distribution_id},
    )
    return get(conn, distribution_id)


# --- Per-car allocation (P-10) ---------------------------------------------------------------------------


def allocate_sale(
    conn: Connection, *, sale_id: UUID, vehicle_id: UUID, sale_date: date, gross_profit: Decimal, label: str
) -> EntryRef | None:
    """With the PER_CAR policy, a posted sale's gross profit goes to the partners
    at once, by the shares in force on the sale date (D-40)."""
    settings = conn.execute(_SETTINGS).mappings().one()
    if settings["profit_policy"] != "PER_CAR" or gross_profit == 0:
        return None
    weights = {s.partner_id: s.percentage for s in partners.shares_on(conn, sale_date)}
    if not weights:
        raise AppError("DISTRIBUTION_SHARES_MISSING", "Partner shares are not set for the sale date", status_code=422)
    shares = allocate(gross_profit, weights, settings["rounding_remainder"])
    allocation_id = uuid4()
    draft = rules.profit_allocation(
        entry_date=sale_date,
        shares=sorted(shares.items(), key=lambda item: -weights[item[0]]),
        description=f"توزيع ربح {label} على الشركاء",
        source_id=allocation_id,
    )
    entry = engine.post(conn, draft)
    conn.execute(
        text(
            """
            insert into public.profit_allocations
              (id, tenant_id, sale_id, vehicle_id, allocation_date, gross_profit, journal_entry_id)
            values (:id, private.current_tenant_id(), :sale, :vehicle, :d, :gross, :entry)
            """
        ),
        {
            "id": allocation_id,
            "sale": sale_id,
            "vehicle": vehicle_id,
            "d": sale_date,
            "gross": gross_profit,
            "entry": entry.id,
        },
    )
    return EntryRef(id=entry.id, entry_no=entry.entry_no)


def reverse_sale_allocation(conn: Connection, sale_id: UUID, reason: str, on_date: date) -> EntryRef | None:
    row = conn.execute(
        text("select id, journal_entry_id from public.profit_allocations where sale_id = :id and status = 'POSTED'"),
        {"id": sale_id},
    ).first()
    if row is None:
        return None
    reversal = engine.reverse(conn, row.journal_entry_id, reason, on_date)
    conn.execute(
        text("update public.profit_allocations set status = 'REVERSED', reversal_entry_id = :r where id = :id"),
        {"r": reversal.id, "id": row.id},
    )
    return EntryRef(id=reversal.id, entry_no=reversal.entry_no)
