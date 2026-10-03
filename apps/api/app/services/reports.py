"""Reports (SPEC §4.12). Every figure is read from the ledger or derived from
documents; nothing is stored. Each report has a typed result where other code
needs the numbers (P&L, trial balance, ledger, balance check) and a
``ReportTable`` for the reports centre and the PDF/Excel exporters.
"""

from collections.abc import Callable
from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import Connection, text

from app.core.errors import AppError, not_found
from app.domain.ledger import ZERO
from app.domain.money import quantize
from app.domain.reports import (
    AccountAmount,
    BalanceCheck,
    ColumnKind,
    GeneralLedger,
    LedgerLine,
    ProfitAndLoss,
    ReportColumn,
    ReportFilters,
    ReportName,
    ReportRow,
    ReportTable,
    TrialBalance,
    TrialBalanceRow,
    money_text,
)
from app.services import consignment, finance, papers, vehicles

# --- Profit and loss ---------------------------------------------------------------------------------------

_PNL = text(
    """
    select a.id, a.code, a.name_ar, a.name_en, a.type,
           sum(case when a.type = 'INCOME' then l.credit - l.debit else l.debit - l.credit end) as amount
      from public.journal_lines l
      join public.journal_entries e on e.id = l.journal_entry_id
      join public.ledger_accounts a on a.id = l.ledger_account_id
     where a.type in ('INCOME', 'EXPENSE') and not e.is_closing
       and l.entry_date between :date_from and :date_to
     group by a.id, a.code, a.name_ar, a.name_en, a.type
    having sum(l.debit - l.credit) <> 0
     order by a.code
    """
)


def _check_range(date_from: date, date_to: date) -> None:
    if date_to < date_from:
        raise AppError("DATE_RANGE_INVALID", "The period ends before it starts", status_code=422)


def profit_and_loss(conn: Connection, date_from: date, date_to: date) -> ProfitAndLoss:
    """Revenue - cost of cars sold (5xxx) = gross profit - other expenses = net profit."""
    _check_range(date_from, date_to)
    rows = list(conn.execute(_PNL, {"date_from": date_from, "date_to": date_to}).mappings())

    def amount(row: Any) -> AccountAmount:
        return AccountAmount(
            account_id=row["id"],
            code=row["code"],
            name_ar=row["name_ar"],
            name_en=row["name_en"],
            amount=Decimal(row["amount"]),
        )

    revenue = [amount(r) for r in rows if r["type"] == "INCOME"]
    cost_of_sales = sum(
        (Decimal(r["amount"]) for r in rows if r["type"] == "EXPENSE" and r["code"].startswith("5")), ZERO
    )
    expenses = [amount(r) for r in rows if r["type"] == "EXPENSE" and not r["code"].startswith("5")]
    revenue_total = sum((r.amount for r in revenue), ZERO)
    expenses_total = sum((e.amount for e in expenses), ZERO)
    gross = revenue_total - cost_of_sales
    return ProfitAndLoss(
        date_from=date_from,
        date_to=date_to,
        revenue=revenue,
        revenue_total=revenue_total,
        cost_of_sales=cost_of_sales,
        gross_profit=gross,
        expenses=expenses,
        expenses_total=expenses_total,
        net_profit=gross - expenses_total,
    )


# --- Trial balance, general ledger, balance check ---------------------------------------------------------


def trial_balance(conn: Connection, as_of: date) -> TrialBalance:
    rows = conn.execute(
        text(
            """
            select a.id, a.code, a.name_ar, a.name_en, a.type, sum(l.debit) as debit, sum(l.credit) as credit
              from public.journal_lines l join public.ledger_accounts a on a.id = l.ledger_account_id
             where l.entry_date <= :as_of
             group by a.id, a.code, a.name_ar, a.name_en, a.type
            having sum(l.debit) <> sum(l.credit)
             order by a.code
            """
        ),
        {"as_of": as_of},
    ).mappings()
    result = []
    for row in rows:
        net = Decimal(row["debit"]) - Decimal(row["credit"])
        result.append(
            TrialBalanceRow(
                account_id=row["id"],
                code=row["code"],
                name_ar=row["name_ar"],
                name_en=row["name_en"],
                type=row["type"],
                debit=net if net > 0 else ZERO,
                credit=-net if net < 0 else ZERO,
            )
        )
    return TrialBalance(
        as_of=as_of,
        rows=result,
        total_debit=sum((r.debit for r in result), ZERO),
        total_credit=sum((r.credit for r in result), ZERO),
    )


def general_ledger(conn: Connection, account_id: UUID, date_from: date, date_to: date) -> GeneralLedger:
    _check_range(date_from, date_to)
    account = conn.execute(
        text("select id, code, name_ar, name_en, normal_side from public.ledger_accounts where id = :id"),
        {"id": account_id},
    ).first()
    if account is None:
        raise not_found("account")
    sign = Decimal(1) if account.normal_side == "DEBIT" else Decimal(-1)
    opening = (
        Decimal(
            conn.execute(
                text(
                    "select coalesce(sum(debit - credit), 0) from public.journal_lines "
                    "where ledger_account_id = :id and entry_date < :d"
                ),
                {"id": account_id, "d": date_from},
            ).scalar_one()
        )
        * sign
    )
    balance = opening
    lines = []
    for row in conn.execute(
        text(
            """
            select e.entry_date, e.entry_no, coalesce(l.memo, e.description) as description, l.debit, l.credit
              from public.journal_lines l join public.journal_entries e on e.id = l.journal_entry_id
             where l.ledger_account_id = :id and l.entry_date between :f and :t
             order by e.entry_date, e.entry_no, l.line_no
            """
        ),
        {"id": account_id, "f": date_from, "t": date_to},
    ):
        balance += (Decimal(row.debit) - Decimal(row.credit)) * sign
        lines.append(
            LedgerLine(
                entry_date=row.entry_date,
                entry_no=row.entry_no,
                description=row.description,
                debit=Decimal(row.debit),
                credit=Decimal(row.credit),
                balance=balance,
            )
        )
    return GeneralLedger(
        account_id=account.id,
        code=account.code,
        name_ar=account.name_ar,
        name_en=account.name_en,
        date_from=date_from,
        date_to=date_to,
        opening=opening,
        lines=lines,
        closing=balance,
    )


def balance_check(conn: Connection, as_of: date) -> BalanceCheck:
    totals = {
        row.type: Decimal(row.net)
        for row in conn.execute(
            text(
                """
                select a.type, coalesce(sum(l.debit - l.credit), 0) as net
                  from public.journal_lines l join public.ledger_accounts a on a.id = l.ledger_account_id
                 where l.entry_date <= :as_of group by a.type
                """
            ),
            {"as_of": as_of},
        )
    }
    assets = totals.get("ASSET", ZERO)
    liabilities = -totals.get("LIABILITY", ZERO)
    equity = -totals.get("EQUITY", ZERO)
    unclosed = -(totals.get("INCOME", ZERO) + totals.get("EXPENSE", ZERO))
    opening_equity = -Decimal(
        conn.execute(
            text(
                "select coalesce(sum(l.debit - l.credit), 0) from public.journal_lines l "
                "join public.ledger_accounts a on a.id = l.ledger_account_id "
                "where a.system_key = 'OPENING_BALANCE_EQUITY' and l.entry_date <= :as_of"
            ),
            {"as_of": as_of},
        ).scalar_one()
    )
    difference = assets - liabilities - equity - unclosed
    notes = []
    if opening_equity != 0:
        notes.append("OPENING_EQUITY_NOT_CLEARED")  # Q-16 / C-07
    return BalanceCheck(
        as_of=as_of,
        assets=assets,
        liabilities=liabilities,
        equity=equity,
        unclosed_profit=unclosed,
        difference=difference,
        balanced=difference == 0,
        opening_equity=opening_equity,
        notes=notes,
    )


# --- Tables ------------------------------------------------------------------------------------------------


def _col(key: str, ar: str, en: str, kind: ColumnKind = "text") -> ReportColumn:
    return ReportColumn(key=key, label_ar=ar, label_en=en, kind=kind)


def _m(value: Decimal | None) -> str | None:
    return money_text(value) if value is not None else None


def _period(date_from: date, date_to: date) -> tuple[str, str]:
    return f"من {date_from} إلى {date_to}", f"{date_from} to {date_to}"


def _table(conn: Connection, name: ReportName, ar: str, en: str, **values: Any) -> ReportTable:
    return ReportTable(name=name, title_ar=ar, title_en=en, currency_code=finance.tenant_info(conn).currency, **values)


def pnl_table(conn: Connection, f: ReportFilters) -> ReportTable:
    date_from, date_to = _range(conn, f)
    pnl = profit_and_loss(conn, date_from, date_to)
    rows = [ReportRow(cells={"name": "الإيرادات|Revenue", "amount": None}, style="section")]
    rows += [ReportRow(cells={"name": f"{r.name_ar}|{r.name_en}", "amount": _m(r.amount)}) for r in pnl.revenue]
    rows.append(
        ReportRow(cells={"name": "إجمالي الإيرادات|Total revenue", "amount": _m(pnl.revenue_total)}, style="total")
    )
    rows.append(ReportRow(cells={"name": "تكلفة السيارات المباعة|Cost of cars sold", "amount": _m(-pnl.cost_of_sales)}))
    rows.append(ReportRow(cells={"name": "مجمل الربح|Gross profit", "amount": _m(pnl.gross_profit)}, style="total"))
    rows.append(ReportRow(cells={"name": "المصروفات|Expenses", "amount": None}, style="section"))
    rows += [ReportRow(cells={"name": f"{e.name_ar}|{e.name_en}", "amount": _m(-e.amount)}) for e in pnl.expenses]
    rows.append(ReportRow(cells={"name": "صافي الربح|Net profit", "amount": _m(pnl.net_profit)}, style="total"))
    period_ar, period_en = _period(date_from, date_to)
    return _table(
        conn,
        "profit-and-loss",
        "الأرباح والخسائر",
        "Profit and loss",
        period_ar=period_ar,
        period_en=period_en,
        columns=[_col("name", "البند", "Item"), _col("amount", "المبلغ", "Amount", "money")],
        rows=rows,
        figures=[
            ("مجمل الربح", "Gross profit", money_text(pnl.gross_profit), "money"),
            ("صافي الربح", "Net profit", money_text(pnl.net_profit), "money"),
        ],
    )


def trial_balance_table(conn: Connection, f: ReportFilters) -> ReportTable:
    as_of = f.as_of or f.date_to or finance.tenant_info(conn).today
    tb = trial_balance(conn, as_of)
    rows = [
        ReportRow(
            cells={
                "code": r.code,
                "name": f"{r.name_ar}|{r.name_en}",
                "debit": _m(r.debit or None),
                "credit": _m(r.credit or None),
            }
        )
        for r in tb.rows
    ]
    rows.append(
        ReportRow(
            cells={"code": "", "name": "الإجمالي|Total", "debit": _m(tb.total_debit), "credit": _m(tb.total_credit)},
            style="total",
        )
    )
    return _table(
        conn,
        "trial-balance",
        "ميزان المراجعة",
        "Trial balance",
        period_ar=f"حتى {as_of}",
        period_en=f"As of {as_of}",
        columns=[
            _col("code", "الكود", "Code"),
            _col("name", "الحساب", "Account"),
            _col("debit", "مدين", "Debit", "money"),
            _col("credit", "دائن", "Credit", "money"),
        ],
        rows=rows,
    )


def general_ledger_table(conn: Connection, f: ReportFilters) -> ReportTable:
    if f.account_id is None:
        raise AppError("VALIDATION_ERROR", "Choose an account", status_code=422)
    date_from, date_to = _range(conn, f)
    gl = general_ledger(conn, f.account_id, date_from, date_to)
    rows = [
        ReportRow(
            cells={
                "date": None,
                "entry": None,
                "description": "رصيد أول المدة|Opening balance",
                "debit": None,
                "credit": None,
                "balance": _m(gl.opening),
            },
            style="section",
        )
    ]
    rows += [
        ReportRow(
            cells={
                "date": line.entry_date.isoformat(),
                "entry": line.entry_no,
                "description": line.description,
                "debit": _m(line.debit or None),
                "credit": _m(line.credit or None),
                "balance": _m(line.balance),
            }
        )
        for line in gl.lines
    ]
    rows.append(
        ReportRow(
            cells={
                "date": None,
                "entry": None,
                "description": "رصيد آخر المدة|Closing balance",
                "debit": None,
                "credit": None,
                "balance": _m(gl.closing),
            },
            style="total",
        )
    )
    period_ar, period_en = _period(date_from, date_to)
    return _table(
        conn,
        "general-ledger",
        f"دفتر الأستاذ — {gl.code} {gl.name_ar}",
        f"General ledger — {gl.code} {gl.name_en}",
        period_ar=period_ar,
        period_en=period_en,
        columns=[
            _col("date", "التاريخ", "Date", "date"),
            _col("entry", "القيد", "Entry", "number"),
            _col("description", "البيان", "Description"),
            _col("debit", "مدين", "Debit", "money"),
            _col("credit", "دائن", "Credit", "money"),
            _col("balance", "الرصيد", "Balance", "money"),
        ],
        rows=rows,
    )


def balance_check_table(conn: Connection, f: ReportFilters) -> ReportTable:
    as_of = f.as_of or f.date_to or finance.tenant_info(conn).today
    check = balance_check(conn, as_of)
    items = [
        ("الأصول|Assets", check.assets, None),
        ("الالتزامات|Liabilities", check.liabilities, None),
        ("حقوق الملكية|Equity", check.equity, None),
        ("أرباح لم تُقفل بعد|Profit not yet closed", check.unclosed_profit, None),
        ("الفرق|Difference", check.difference, "total"),
    ]
    if check.opening_equity:
        items.append(
            ("أرصدة افتتاحية لم تُوزَّع (3900)|Opening balance equity not cleared (3900)", check.opening_equity, "muted")
        )
    return _table(
        conn,
        "balance-check",
        "مطابقة الميزانية",
        "Balance check",
        period_ar=f"حتى {as_of}",
        period_en=f"As of {as_of}",
        columns=[_col("name", "البند", "Item"), _col("amount", "المبلغ", "Amount", "money")],
        rows=[ReportRow(cells={"name": n, "amount": _m(v)}, style=s) for n, v, s in items],
        figures=[("متوازنة", "Balanced", "✓" if check.balanced else "✗", "text")],
    )


def vehicle_profit_table(conn: Connection, f: ReportFilters) -> ReportTable:
    date_from, date_to = _range(conn, f)
    sold = list(
        conn.execute(
            text(
                """
                select s.id as sale_id, s.sale_no, s.sale_date, s.sale_price, s.channel, v.id as vehicle_id, v.stock_no,
                       concat_ws(' ', v.make, v.model, v.year) as label, v.ownership_type, v.stock_date
                  from public.sales s join public.vehicles v on v.id = s.vehicle_id
                 where s.status = 'POSTED' and s.sale_date between :f and :t
                 order by s.sale_date, s.sale_no
                """
            ),
            {"f": date_from, "t": date_to},
        ).mappings()
    )
    totals = vehicles.cost_totals(conn, [row["vehicle_id"] for row in sold]) if sold else {}
    rows = []
    sum_price = sum_cost = sum_profit = ZERO
    for row in sold:
        t = totals[row["vehicle_id"]]
        price = Decimal(row["sale_price"])
        if row["ownership_type"] == "CONSIGNED_IN":
            cost, profit, commission = t.consignment_expense, t.commission - t.consignment_expense, None
        else:
            cost, profit, commission = t.cogs, t.sales - t.cogs - t.external_commission, t.external_commission or None
        days = (row["sale_date"] - row["stock_date"]).days if row["stock_date"] else None
        sum_price += price
        sum_cost += cost
        sum_profit += profit
        rows.append(
            ReportRow(
                cells={
                    "stock_no": row["stock_no"],
                    "vehicle": row["label"],
                    "sale_no": row["sale_no"],
                    "sale_date": row["sale_date"].isoformat(),
                    "sale_price": _m(price),
                    "cost": _m(cost),
                    "commission": _m(commission),
                    "profit": _m(profit),
                    "pct": money_text(quantize(profit * 100 / price)) if price else None,
                    "days": days,
                },
                link=["vehicles", str(row["vehicle_id"])],
            )
        )
    rows.append(
        ReportRow(
            cells={
                "stock_no": "",
                "vehicle": "الإجمالي|Total",
                "sale_price": _m(sum_price),
                "cost": _m(sum_cost),
                "profit": _m(sum_profit),
            },
            style="total",
        )
    )
    period_ar, period_en = _period(date_from, date_to)
    return _table(
        conn,
        "vehicle-profit",
        "ربح السيارات",
        "Vehicle profit",
        period_ar=period_ar,
        period_en=period_en,
        columns=[
            _col("stock_no", "رقم المخزون", "Stock no."),
            _col("vehicle", "السيارة", "Vehicle"),
            _col("sale_no", "البيع", "Sale"),
            _col("sale_date", "تاريخ البيع", "Sale date", "date"),
            _col("sale_price", "سعر البيع", "Sale price", "money"),
            _col("cost", "التكلفة", "Cost", "money"),
            _col("commission", "عمولة معرض آخر", "External commission", "money"),
            _col("profit", "الربح", "Profit", "money"),
            _col("pct", "٪", "%", "percent"),
            _col("days", "أيام في المخزون", "Days in stock", "number"),
        ],
        rows=rows,
        figures=[("إجمالي الربح", "Total profit", money_text(sum_profit), "money")],
    )


_BUCKETS = ((0, 30, "0–30"), (31, 60, "31–60"), (61, 90, "61–90"), (91, None, "90+"))


def inventory_aging_table(conn: Connection, f: ReportFilters) -> ReportTable:
    """Cars in stock by age (SPEC §4.12 #5: 0-30, 31-60, 61-90, 90+ days)."""
    today = finance.tenant_info(conn).today
    stock = list(
        conn.execute(
            text(
                """
                select v.id, v.stock_no, concat_ws(' ', v.make, v.model, v.year) as label, v.status, v.ownership_type,
                       v.stock_date, v.asking_price
                  from public.vehicles v
                 where v.status in ('IN_PREPARATION', 'AVAILABLE', 'RESERVED', 'AT_OTHER_SHOWROOM')
                 order by v.stock_date nulls last, v.stock_no
                """
            )
        ).mappings()
    )
    totals = vehicles.cost_totals(conn, [row["id"] for row in stock]) if stock else {}
    bucket_count = {label: 0 for *_, label in _BUCKETS}
    bucket_cost = {label: ZERO for *_, label in _BUCKETS}
    rows = []
    for row in stock:
        days = (today - row["stock_date"]).days if row["stock_date"] else 0
        label = next(lbl for low, high, lbl in _BUCKETS if days >= low and (high is None or days <= high))
        cost = totals[row["id"]].total_cost
        bucket_count[label] += 1
        bucket_cost[label] += cost
        rows.append(
            ReportRow(
                cells={
                    "stock_no": row["stock_no"],
                    "vehicle": row["label"],
                    "status": row["status"],
                    "consigned": "✓" if row["ownership_type"] == "CONSIGNED_IN" else "",
                    "days": days,
                    "bucket": label,
                    "cost": _m(cost),
                    "asking": _m(row["asking_price"]),
                },
                link=["vehicles", str(row["id"])],
            )
        )
    figures = [
        (f"{label} يوم", f"{label} days", f"{bucket_count[label]} · {money_text(bucket_cost[label])}", "text")
        for *_, label in _BUCKETS
    ]
    return _table(
        conn,
        "inventory-aging",
        "أعمار المخزون",
        "Inventory aging",
        period_ar=f"حتى {today}",
        period_en=f"As of {today}",
        columns=[
            _col("stock_no", "رقم المخزون", "Stock no."),
            _col("vehicle", "السيارة", "Vehicle"),
            _col("status", "الحالة", "Status"),
            _col("consigned", "أمانة", "Consigned"),
            _col("days", "الأيام", "Days", "number"),
            _col("bucket", "الفئة", "Bucket"),
            _col("cost", "التكلفة", "Cost", "money"),
            _col("asking", "سعر العرض", "Asking price", "money"),
        ],
        rows=rows,
        figures=figures,
    )


def expenses_by_category_table(conn: Connection, f: ReportFilters) -> ReportTable:
    date_from, date_to = _range(conn, f)
    rows_db = conn.execute(
        text(
            """
            select a.code, a.name_ar, a.name_en, sum(l.debit - l.credit) as amount,
                   count(distinct l.journal_entry_id) as entries
              from public.journal_lines l
              join public.journal_entries e on e.id = l.journal_entry_id
              join public.ledger_accounts a on a.id = l.ledger_account_id
              join public.ledger_accounts p on p.id = a.parent_id
             where p.system_key = 'GENERAL_EXPENSES' and not e.is_closing and l.entry_date between :f and :t
             group by a.code, a.name_ar, a.name_en
            having sum(l.debit - l.credit) <> 0
             order by a.code
            """
        ),
        {"f": date_from, "t": date_to},
    ).mappings()
    rows, total = [], ZERO
    for r in rows_db:
        total += Decimal(r["amount"])
        rows.append(
            ReportRow(
                cells={
                    "code": r["code"],
                    "name": f"{r['name_ar']}|{r['name_en']}",
                    "entries": r["entries"],
                    "amount": _m(Decimal(r["amount"])),
                }
            )
        )
    rows.append(
        ReportRow(cells={"code": "", "name": "الإجمالي|Total", "entries": None, "amount": _m(total)}, style="total")
    )
    period_ar, period_en = _period(date_from, date_to)
    return _table(
        conn,
        "expenses-by-category",
        "المصروفات العامة حسب البند",
        "General expenses by category",
        period_ar=period_ar,
        period_en=period_en,
        columns=[
            _col("code", "الكود", "Code"),
            _col("name", "البند", "Category"),
            _col("entries", "عدد القيود", "Entries", "number"),
            _col("amount", "المبلغ", "Amount", "money"),
        ],
        rows=rows,
        figures=[("الإجمالي", "Total", money_text(total), "money")],
    )


def installment_collections_table(conn: Connection, f: ReportFilters) -> ReportTable:
    date_from, date_to = _range(conn, f)
    rows_db = conn.execute(
        text(
            """
            select r.receipt_date, c.name as customer, s.sale_no, r.amount, r.status,
                   coalesce(ca.name_ar, 'رصيد العميل') as account, je.entry_no, p.id as plan_id
              from public.customer_receipts r
              join public.customers c on c.id = r.customer_id
              join public.installment_plans p on p.id = r.plan_id
              join public.sales s on s.id = p.sale_id
              left join public.cash_accounts ca on ca.id = r.cash_account_id
              join public.journal_entries je on je.id = r.journal_entry_id
             where r.receipt_date between :f and :t
             order by r.receipt_date, je.entry_no
            """
        ),
        {"f": date_from, "t": date_to},
    ).mappings()
    rows, total = [], ZERO
    for r in rows_db:
        counted = r["status"] == "POSTED"
        if counted:
            total += Decimal(r["amount"])
        rows.append(
            ReportRow(
                cells={
                    "date": r["receipt_date"].isoformat(),
                    "customer": r["customer"],
                    "sale": r["sale_no"],
                    "account": r["account"],
                    "status": r["status"],
                    "amount": _m(Decimal(r["amount"])),
                },
                style=None if counted else "muted",
                link=["installments", "plans", str(r["plan_id"])],
            )
        )
    rows.append(ReportRow(cells={"date": None, "customer": "الإجمالي|Total", "amount": _m(total)}, style="total"))
    period_ar, period_en = _period(date_from, date_to)
    return _table(
        conn,
        "installment-collections",
        "تحصيلات الأقساط",
        "Installment collections",
        period_ar=period_ar,
        period_en=period_en,
        columns=[
            _col("date", "التاريخ", "Date", "date"),
            _col("customer", "العميل", "Customer"),
            _col("sale", "البيع", "Sale"),
            _col("account", "الخزنة / البنك", "Cash / bank"),
            _col("status", "الحالة", "Status"),
            _col("amount", "المبلغ", "Amount", "money"),
        ],
        rows=rows,
        figures=[("المحصّل", "Collected", money_text(total), "money")],
    )


def papers_table(conn: Connection, f: ReportFilters) -> ReportTable:
    items = papers.list_papers(conn)
    rows = [
        ReportRow(
            cells={
                "type": p.paper_type,
                "number": p.number,
                "customer": p.customer_name,
                "sale": p.sale_no,
                "due": p.due_date.isoformat(),
                "status": p.status,
                "overdue": "✓" if p.overdue else "",
                "amount": _m(p.amount),
            },
            style="muted" if p.status in ("COLLECTED", "RETURNED") else None,
        )
        for p in items
    ]
    return _table(
        conn,
        "deferred-papers",
        "سجل الأوراق الآجلة",
        "Deferred papers register",
        columns=[
            _col("type", "النوع", "Type"),
            _col("number", "الرقم", "Number"),
            _col("customer", "العميل", "Customer"),
            _col("sale", "البيع", "Sale"),
            _col("due", "الاستحقاق", "Due", "date"),
            _col("status", "الحالة", "Status"),
            _col("overdue", "متأخرة", "Overdue"),
            _col("amount", "المبلغ", "Amount", "money"),
        ],
        rows=rows,
    )


def consignments_in_table(conn: Connection, f: ReportFilters) -> ReportTable:
    items = consignment.list_consignments(conn, status=None, consignor_id=None, q=None, with_money=True)
    rows = [
        ReportRow(
            cells={
                "stock_no": c.stock_no,
                "vehicle": c.vehicle_label,
                "owner": c.consignor_name,
                "terms": c.terms_type,
                "status": c.status,
                "days": c.days_with_us,
                "commission": _m(c.commission),
                "payable": _m(c.payable),
                "recoverable": _m(c.recoverable),
            },
            link=["consignments", str(c.id)],
        )
        for c in items
    ]
    return _table(
        conn,
        "consignments-in",
        "سيارات الأمانة عندنا",
        "Consignments in",
        columns=[
            _col("stock_no", "رقم المخزون", "Stock no."),
            _col("vehicle", "السيارة", "Vehicle"),
            _col("owner", "صاحبها", "Owner"),
            _col("terms", "الشروط", "Terms"),
            _col("status", "الحالة", "Status"),
            _col("days", "أيام عندنا", "Days", "number"),
            _col("commission", "العمولة", "Commission", "money"),
            _col("payable", "مستحق له", "Owed to owner", "money"),
            _col("recoverable", "مستحق عليه", "Owed by owner", "money"),
        ],
        rows=rows,
    )


def consignments_out_table(conn: Connection, f: ReportFilters) -> ReportTable:
    items = consignment.list_out(conn, status=None, showroom_id=None)
    rows = [
        ReportRow(
            cells={
                "stock_no": o.stock_no,
                "vehicle": o.vehicle_label,
                "showroom": o.external_showroom_name,
                "sent": o.sent_date.isoformat(),
                "days": o.days_out,
                "status": o.status,
                "sale_price": _m(o.sale_price),
            },
            link=["vehicles", str(o.vehicle_id)],
        )
        for o in items
    ]
    return _table(
        conn,
        "consignments-out",
        "سياراتنا عند معارض أخرى",
        "Consignments out",
        columns=[
            _col("stock_no", "رقم المخزون", "Stock no."),
            _col("vehicle", "السيارة", "Vehicle"),
            _col("showroom", "المعرض", "Showroom"),
            _col("sent", "أُرسلت", "Sent", "date"),
            _col("days", "الأيام", "Days", "number"),
            _col("status", "الحالة", "Status"),
            _col("sale_price", "سعر البيع", "Sale price", "money"),
        ],
        rows=rows,
    )


def _range(conn: Connection, f: ReportFilters) -> tuple[date, date]:
    today = finance.tenant_info(conn).today
    date_to = f.date_to or today
    date_from = f.date_from or date_to.replace(day=1)
    _check_range(date_from, date_to)
    return date_from, date_to


BUILDERS: dict[ReportName, Callable[[Connection, ReportFilters], ReportTable]] = {
    "profit-and-loss": pnl_table,
    "trial-balance": trial_balance_table,
    "general-ledger": general_ledger_table,
    "balance-check": balance_check_table,
    "vehicle-profit": vehicle_profit_table,
    "inventory-aging": inventory_aging_table,
    "expenses-by-category": expenses_by_category_table,
    "installment-collections": installment_collections_table,
    "deferred-papers": papers_table,
    "consignments-in": consignments_in_table,
    "consignments-out": consignments_out_table,
}
