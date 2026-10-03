"""Dashboard (SPEC §4.12 #1, §9.2): one call, blocks by permission.

Owner and accountant see money (cash, bank, capital tied up in stock, profit,
partner equity matrix); staff see operations (stock, aging, sales count,
installments due); a partner gets their own position from the partner pages.
"""

from collections.abc import Callable
from decimal import Decimal

from sqlalchemy import Connection, text

from app.domain.dashboard import DashboardOut, EquityRow, KpiTiles
from app.domain.ledger import ZERO
from app.services import attention, finance, installments, partners, vehicles

Can = Callable[[str], bool]


def build(conn: Connection, can: Can, *, installments_enabled: bool) -> DashboardOut:
    today = finance.tenant_info(conn).today
    aging = list(conn.execute(text("select aging_thresholds from public.tenant_settings")).scalar_one())
    financial = can("dashboard.financial")

    stock = list(
        conn.execute(
            text(
                "select id, stock_date from public.vehicles "
                "where status in ('IN_PREPARATION', 'AVAILABLE', 'RESERVED', 'AT_OTHER_SHOWROOM')"
            )
        )
    )
    aged = sum(1 for car in stock if car.stock_date is not None and (today - car.stock_date).days > aging[1])
    sales = list(
        conn.execute(
            text(
                "select vehicle_id, sale_price from public.sales where status = 'POSTED' "
                "and sale_date between :f and :t"
            ),
            {"f": today.replace(day=1), "t": today},
        )
    )
    kpis = KpiTiles(stock_count=len(stock), aged_count=aged, aged_days=aging[1], month_sales_count=len(sales))
    if financial and can("cash.view"):
        accounts = finance.list_cash_accounts(conn)
        kpis.cash_total = sum((a.balance for a in accounts if a.kind == "CASH_BOX"), ZERO)
        kpis.bank_total = sum((a.balance for a in accounts if a.kind != "CASH_BOX"), ZERO)
    if can("vehicle.view_cost"):
        ids = [car.id for car in stock]
        costs = vehicles.cost_totals(conn, ids) if ids else {}
        kpis.stock_cost = sum((c.inventory for c in costs.values()), ZERO)
        sold = vehicles.cost_totals(conn, [s.vehicle_id for s in sales]) if sales else {}
        kpis.month_sales_total = sum((Decimal(s.sale_price) for s in sales), ZERO)
        kpis.month_gross_profit = sum(
            (
                t.commission - t.consignment_expense if t.commission else t.sales - t.cogs - t.external_commission
                for t in sold.values()
            ),
            ZERO,
        )

    out = DashboardOut(as_of=today.isoformat(), kpis=kpis, attention=attention.alerts(conn, can))
    if installments_enabled and can("installment.view"):
        out.installments = installments.kpis(conn)
    if financial and can("partner.view_all"):
        summary = partners.summary(conn, today)
        out.equity = [
            EquityRow(
                partner_id=row.partner_id,
                name_ar=row.name_ar,
                name_en=row.name_en,
                percentage=row.percentage,
                capital=row.capital,
                allocated_profit=row.allocated_profit,
                drawings=row.drawings,
                net=row.net,
            )
            for row in summary.rows
        ]
    return out
