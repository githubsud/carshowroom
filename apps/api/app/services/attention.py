"""Needs Attention engine (SPEC §4.17): deterministic rules, not AI.

Every rule reads current data, uses the tenant's thresholds
(``tenant_settings.attention_thresholds``, ``aging_thresholds``) and runs only
for users holding its permission, so sales staff never get profit alerts.
The output order is fixed: danger, then warn, then info; within a level by
rule and then by the record's own order.
"""

from collections.abc import Callable
from datetime import timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import Connection, text

from app.domain.dashboard import AttentionItem
from app.domain.ledger import ZERO
from app.domain.reports import money_text
from app.services import crm, finance, installments, vehicles

Can = Callable[[str], bool]
_SEVERITY = {"danger": 0, "warn": 1, "info": 2}
LIMIT_PER_RULE = 20


def _thresholds(conn: Connection) -> tuple[dict[str, Any], list[int]]:
    row = conn.execute(text("select attention_thresholds, aging_thresholds from public.tenant_settings")).one()
    return dict(row.attention_thresholds or {}), list(row.aging_thresholds)


def _installments(conn: Connection, settings: dict[str, Any]) -> list[AttentionItem]:
    today = finance.tenant_info(conn).today
    hours = int(settings.get("dashboard_due_hours", 48))
    soon = today + timedelta(days=max(hours // 24, 0))
    rows = installments.list_installments(conn, view="open", days=7, customer_id=None, date_from=None, date_to=None)
    items: list[AttentionItem] = []
    overdue: dict[Any, list[Any]] = {}
    for row in rows:
        if row.state == "OVERDUE":
            overdue.setdefault(row.plan_id, []).append(row)
    for plan_id, late in overdue.items():
        first = late[0]
        items.append(
            AttentionItem(
                kind="INSTALLMENT_OVERDUE",
                severity="danger",
                params={
                    "customer": first.customer_name,
                    "count": len(late),
                    "amount": money_text(sum((r.remaining for r in late), ZERO)),
                    "days": max(r.days_late for r in late),
                },
                entity_type="INSTALLMENT_PLAN",
                entity_id=plan_id,
                link=["installments", "plans", str(plan_id)],
            )
        )
    for row in rows:
        if row.state != "OVERDUE" and today <= row.due_date <= soon:
            items.append(
                AttentionItem(
                    kind="INSTALLMENT_DUE_SOON",
                    severity="warn",
                    params={
                        "customer": row.customer_name,
                        "seq": row.seq,
                        "amount": money_text(row.remaining),
                        "due_date": row.due_date.isoformat(),
                    },
                    entity_type="INSTALLMENT_PLAN",
                    entity_id=row.plan_id,
                    link=["installments", "plans", str(row.plan_id)],
                )
            )
    for paper in conn.execute(
        text(
            "select p.id, p.number, p.amount, c.name from public.deferred_papers p "
            "join public.customers c on c.id = p.customer_id where p.status = 'BOUNCED' order by p.due_date"
        )
    ):
        items.append(
            AttentionItem(
                kind="CHEQUE_BOUNCED",
                severity="danger",
                params={"number": paper.number, "customer": paper.name, "amount": money_text(Decimal(paper.amount))},
                entity_type="DEFERRED_PAPER",
                entity_id=paper.id,
                link=["installments", "papers"],
            )
        )
    return items


_STOCK = """
    select v.id, v.stock_no, concat_ws(' ', v.make, v.model, v.year) as label, v.stock_date, v.license_expiry,
           v.asking_price, v.ownership_type
      from public.vehicles v
     where v.status in ('IN_PREPARATION', 'AVAILABLE', 'RESERVED', 'AT_OTHER_SHOWROOM')
     order by v.stock_date nulls last, v.stock_no
"""


def _vehicles(conn: Connection, settings: dict[str, Any], aging: list[int], can: Can) -> list[AttentionItem]:
    today = finance.tenant_info(conn).today
    stock = list(conn.execute(text(_STOCK)).mappings())
    items: list[AttentionItem] = []
    license_days = int(settings.get("license_expiry_days", 30))
    for car in stock:
        link = ["vehicles", str(car["id"])]
        if car["stock_date"] is not None:
            days = (today - car["stock_date"]).days
            if days >= aging[1]:
                items.append(
                    AttentionItem(
                        kind="VEHICLE_AGING",
                        severity="danger" if days >= aging[2] else "warn",
                        params={"vehicle": car["label"], "stock_no": car["stock_no"], "days": days},
                        entity_type="VEHICLE",
                        entity_id=car["id"],
                        link=link,
                    )
                )
        expiry = car["license_expiry"]
        if expiry is not None and expiry <= today + timedelta(days=license_days):
            items.append(
                AttentionItem(
                    kind="LICENSE_EXPIRY",
                    severity="danger" if expiry < today else "warn",
                    params={"vehicle": car["label"], "stock_no": car["stock_no"], "date": expiry.isoformat()},
                    entity_type="VEHICLE",
                    entity_id=car["id"],
                    link=link,
                )
            )
    if not can("vehicle.view_cost") or not stock:
        return items
    owned = [car for car in stock if car["ownership_type"] == "OWNED"]
    ids = [car["id"] for car in owned]
    missing = vehicles.missing_categories(conn, ids) if ids else {}
    totals = vehicles.cost_totals(conn, ids) if ids else {}
    min_profit = Decimal(str(settings.get("min_profit", "0")))
    for car in owned:
        link = ["vehicles", str(car["id"])]
        if missing.get(car["id"]):
            items.append(
                AttentionItem(
                    kind="COST_INCOMPLETE",
                    severity="info",
                    params={
                        "vehicle": car["label"],
                        "stock_no": car["stock_no"],
                        "missing": "، ".join(missing[car["id"]]),
                    },
                    entity_type="VEHICLE",
                    entity_id=car["id"],
                    link=link,
                )
            )
        cost = totals[car["id"]].total_cost
        if car["asking_price"] is not None and cost > 0 and Decimal(car["asking_price"]) - cost < min_profit:
            items.append(
                AttentionItem(
                    kind="LOW_PROFIT",
                    severity="warn",
                    params={
                        "vehicle": car["label"],
                        "stock_no": car["stock_no"],
                        "profit": money_text(Decimal(car["asking_price"]) - cost),
                    },
                    entity_type="VEHICLE",
                    entity_id=car["id"],
                    link=link,
                )
            )
    return items


def _customers(conn: Connection, settings: dict[str, Any]) -> list[AttentionItem]:
    items: list[AttentionItem] = []
    for row in conn.execute(
        text(
            """
            select v.id, v.stock_no, concat_ws(' ', v.make, v.model, v.year) as label, count(*) as waiting
              from public.customer_request_matches m
              join public.customer_requests r on r.id = m.request_id
              join public.vehicles v on v.id = m.vehicle_id
             where not m.contacted and v.status = 'AVAILABLE'
               and r.status in ('NEW', 'CONTACTED', 'VEHICLE_FOUND', 'NEGOTIATING')
             group by v.id, v.stock_no, v.make, v.model, v.year
             order by count(*) desc, v.stock_no
            """
        )
    ):
        items.append(
            AttentionItem(
                kind="REQUEST_MATCH",
                severity="warn",
                params={"vehicle": row.label, "stock_no": row.stock_no, "count": row.waiting},
                entity_type="VEHICLE",
                entity_id=row.id,
                link=["vehicles", str(row.id)],
            )
        )
    for due in crm.due_follow_ups(conn, assigned_to=None):
        f = due.follow_up
        items.append(
            AttentionItem(
                kind="FOLLOW_UP_DUE",
                severity="danger" if f.priority == "HIGH" else "warn",
                params={"customer": f.customer_name, "phone": f.customer_phone, "days": due.overdue_days},
                entity_type="CUSTOMER",
                entity_id=f.customer_id,
                link=["customers", str(f.customer_id)],
            )
        )
    idle_days = int(settings.get("lead_idle_days", 7))
    today = finance.tenant_info(conn).today
    for row in conn.execute(
        text(
            """
            select r.id, r.customer_id, c.name, concat_ws(' ', r.make, r.model) as wants,
                   greatest(r.created_at::date, coalesce(max(f.occurred_at)::date, r.created_at::date)) as last_touch
              from public.customer_requests r
              join public.customers c on c.id = r.customer_id
              left join public.follow_ups f on f.customer_id = r.customer_id
             where r.status in ('NEW', 'CONTACTED', 'VEHICLE_FOUND', 'NEGOTIATING')
             group by r.id, r.customer_id, c.name, r.make, r.model, r.created_at
            having greatest(r.created_at::date, coalesce(max(f.occurred_at)::date, r.created_at::date)) <= :cutoff
             order by last_touch
            """
        ),
        {"cutoff": today - timedelta(days=idle_days)},
    ):
        items.append(
            AttentionItem(
                kind="LEAD_IDLE",
                severity="info",
                params={"customer": row.name, "wants": row.wants, "days": (today - row.last_touch).days},
                entity_type="CUSTOMER",
                entity_id=row.customer_id,
                link=["customers", str(row.customer_id)],
            )
        )
    return items


def _money(conn: Connection, can: Can) -> list[AttentionItem]:
    items: list[AttentionItem] = []
    if can("consignment.settle"):
        for row in conn.execute(
            text(
                """
                select ci.id, c.name, concat_ws(' ', v.make, v.model, v.year) as label,
                       -coalesce((select sum(l.debit - l.credit) from public.journal_lines l
                                   join public.ledger_accounts a on a.id = l.ledger_account_id
                                  where a.system_key = 'CONSIGNOR_PAYABLE' and l.consignor_id = ci.consignor_id
                                    and l.vehicle_id = ci.vehicle_id), 0) as payable
                  from public.consignments_in ci
                  join public.customers c on c.id = ci.consignor_id
                  join public.vehicles v on v.id = ci.vehicle_id
                 where ci.status = 'SOLD'
                 order by ci.agreement_date
                """
            )
        ):
            if row.payable > 0:
                items.append(
                    AttentionItem(
                        kind="CONSIGNOR_SETTLEMENT",
                        severity="warn",
                        params={"owner": row.name, "vehicle": row.label, "amount": money_text(Decimal(row.payable))},
                        entity_type="CONSIGNMENT",
                        entity_id=row.id,
                        link=["consignments", str(row.id)],
                    )
                )
    if can("supplier.manage"):
        for row in conn.execute(
            text(
                """
                select s.id, s.name, sum(l.credit - l.debit) as owed
                  from public.journal_lines l
                  join public.ledger_accounts a on a.id = l.ledger_account_id
                  join public.suppliers s on s.id = l.supplier_id
                 where a.system_key = 'SUPPLIER_PAYABLE'
                 group by s.id, s.name having sum(l.credit - l.debit) > 0
                 order by s.name
                """
            )
        ):
            items.append(
                AttentionItem(
                    kind="SUPPLIER_PAYABLE",
                    severity="info",
                    params={"supplier": row.name, "amount": money_text(Decimal(row.owed))},
                    entity_type="SUPPLIER",
                    entity_id=row.id,
                    link=["suppliers"],
                )
            )
    if can("cash.view"):
        for account in finance.list_cash_accounts(conn):
            if account.balance < 0:
                items.append(
                    AttentionItem(
                        kind="CASH_NEGATIVE",
                        severity="danger",
                        params={
                            "account": account.name_ar,
                            "account_en": account.name_en,
                            "amount": money_text(account.balance),
                        },
                        entity_type="CASH_ACCOUNT",
                        entity_id=account.id,
                        link=["finance", "cash"],
                    )
                )
    if can("partner.view_all"):
        for row in conn.execute(
            text(
                """
                select p.id, p.name_ar, sum(l.credit - l.debit) as current
                  from public.journal_lines l
                  join public.ledger_accounts a on a.id = l.ledger_account_id
                  join public.partners p on p.id = l.partner_id
                 where a.system_key = 'PARTNER_CURRENT'
                 group by p.id, p.name_ar having sum(l.credit - l.debit) < 0
                 order by p.name_ar
                """
            )
        ):
            # Q-17 default: drawings exceed the balance when the current account goes negative.
            items.append(
                AttentionItem(
                    kind="PARTNER_OVERDRAWN",
                    severity="warn",
                    params={"partner": row.name_ar, "amount": money_text(Decimal(row.current))},
                    entity_type="PARTNER",
                    entity_id=row.id,
                    link=["partners", str(row.id)],
                )
            )
    return items


def alerts(conn: Connection, can: Can) -> list[AttentionItem]:
    settings, aging = _thresholds(conn)
    groups: list[list[AttentionItem]] = []
    if can("installment.view"):
        groups.append(_installments(conn, settings))
    if can("vehicle.view"):
        groups.append(_vehicles(conn, settings, aging, can))
    if can("customer.view"):
        groups.append(_customers(conn, settings))
    groups.append(_money(conn, can))
    items: list[AttentionItem] = []
    for group in groups:
        per_kind: dict[str, int] = {}
        for item in group:
            per_kind[item.kind] = per_kind.get(item.kind, 0) + 1
            if per_kind[item.kind] <= LIMIT_PER_RULE:
                items.append(item)
    # Stable sort: severity first, rule order and record order kept within a level.
    return sorted(items, key=lambda item: _SEVERITY[item.severity])
