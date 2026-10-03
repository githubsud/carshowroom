"""Phase 7: period close and distribution against the ledger (BACKLOG 7.1, 7.2),
in fresh showrooms so every balance starts at zero."""

import uuid
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import Connection, text

from app.core.errors import AppError
from app.domain.distribution import DistributionIn
from app.domain.finance import CashAccountIn, GeneralExpenseIn
from app.domain.partners import PartnerIn, PartnerTransactionIn, ShareChangeIn
from app.domain.sales import SaleCancelIn, SaleDraftIn
from app.domain.vehicles import CustomerIn, PurchaseIn, VehicleIn
from app.services import customers, distribution, finance, partners, reports, sales, vehicles
from tests.integration.conftest import FRESH_TENANT_ACTOR as OWNER
from tests.integration.test_vehicles_sales import _NoCipher

D = Decimal


class _Showroom:
    """A fresh showroom with a cash box, a bank and two or three partners."""

    def __init__(self, conn: Connection, shares: dict[str, str], since: date) -> None:
        self.conn = conn
        self.cash = finance.create_cash_account(
            conn, CashAccountIn(kind="CASH_BOX", name_ar="الخزنة", is_default=True)
        ).id
        self.bank = finance.create_cash_account(conn, CashAccountIn(kind="BANK", name_ar="بنك")).id
        self.partners = {
            key: partners.create_partner(conn, PartnerIn(name_ar=key), _NoCipher()).id  # type: ignore[arg-type]
            for key in shares
        }
        self.set_shares(since, shares)
        self.seller = customers.create_customer(conn, CustomerIn(name="بائع"), _NoCipher()).id  # type: ignore[arg-type]
        self.buyer = customers.create_customer(conn, CustomerIn(name="مشتري"), _NoCipher()).id  # type: ignore[arg-type]
        self.contribute(since, "1000000")

    def set_shares(self, since: date, shares: dict[str, str]) -> None:
        partners.change_shares(
            self.conn,
            ShareChangeIn.model_validate(
                {
                    "effective_from": since,
                    "shares": [{"partner_id": self.partners[k], "percentage": v} for k, v in shares.items()],
                }
            ),
        )

    def contribute(self, day: date, amount: str) -> None:
        first = next(iter(self.partners.values()))
        partners.record_transaction(
            self.conn,
            first,
            PartnerTransactionIn.model_validate(
                {"type": "CONTRIBUTION", "txn_date": day, "amount": amount, "cash_account_id": self.bank}
            ),
        )

    def sell_car(self, day: date, cost: str, price: str) -> Any:
        car = vehicles.create_vehicle(self.conn, VehicleIn(make="Kia", model="Rio", year=2020))
        vehicles.record_purchase(
            self.conn,
            car,
            PurchaseIn.model_validate(
                {
                    "seller_customer_id": self.seller,
                    "purchase_date": day,
                    "price": cost,
                    "payments": [{"cash_account_id": self.bank, "amount": cost}],
                    "ready_for_sale": True,
                }
            ),
        )
        draft = sales.create_draft(
            self.conn,
            SaleDraftIn.model_validate(
                {
                    "vehicle_id": car,
                    "buyer_customer_id": self.buyer,
                    "sale_date": day,
                    "list_price": price,
                    "payments": [{"cash_account_id": self.cash, "amount": price}],
                }
            ),
            viewer_id=OWNER,
            see_all_drafts=True,
            with_profit=True,
        )
        return sales.post_sale(self.conn, draft.id, user_id=OWNER, with_profit=True)

    def expense(self, day: date, amount: str) -> None:
        category = self.conn.execute(
            text("select id from public.expense_categories where kind = 'GENERAL' and code = 'rent'")
        ).scalar_one()
        finance.record_expense(
            self.conn,
            GeneralExpenseIn.model_validate(
                {"expense_date": day, "category_id": category, "amount": amount, "cash_account_id": self.cash}
            ),
        )

    def current(self, key: str) -> Decimal:
        value = self.conn.execute(
            text(
                "select coalesce(sum(l.credit - l.debit), 0) from public.journal_lines l "
                "join public.ledger_accounts a on a.id = l.ledger_account_id "
                "where a.system_key = 'PARTNER_CURRENT' and l.partner_id = :p"
            ),
            {"p": self.partners[key]},
        ).scalar_one()
        return D(value)

    def account(self, key: str) -> Decimal:
        value = self.conn.execute(
            text(
                "select coalesce(sum(l.debit - l.credit), 0) from public.journal_lines l "
                "join public.ledger_accounts a on a.id = l.ledger_account_id where a.system_key = :k"
            ),
            {"k": key},
        ).scalar_one()
        return D(value)


def _settings(conn: Connection, **values: str) -> None:
    assignments = ", ".join(f"{key} = :{key}" for key in values)
    conn.execute(text(f"update public.tenant_settings set {assignments}"), values)  # noqa: S608 - test keys


def _days(conn: Connection) -> tuple[date, date, date]:
    today = finance.tenant_info(conn).today
    return today - timedelta(days=20), today - timedelta(days=10), today - timedelta(days=1)


def test_a_period_is_closed_once_and_nothing_can_be_posted_into_it(fresh_tenant: tuple[Connection, uuid.UUID]) -> None:
    conn, _ = fresh_tenant
    start, middle, end = _days(conn)
    shop = _Showroom(conn, {"A": "60", "B": "40"}, start)
    shop.sell_car(middle, "100000", "130000")
    shop.expense(middle, "5000")

    payload = DistributionIn(period_from=start, period_to=end)
    preview = distribution.preview(conn, payload)
    assert (preview.revenue, preview.expenses, preview.net_profit) == (D("130000.00"), D("105000.00"), D("25000.00"))
    posted = distribution.post(conn, payload, user_id=OWNER)
    assert len(posted.journal_entries) == 2
    assert (shop.current("A"), shop.current("B")) == (D("15000.00"), D("10000.00"))
    assert shop.account("RETAINED_EARNINGS") == 0

    with pytest.raises(AppError) as twice:
        distribution.preview(conn, payload)
    assert twice.value.code == "DISTRIBUTION_PERIOD_OVERLAP"
    with pytest.raises(AppError) as back_dated, conn.begin_nested():
        shop.expense(middle, "100")
    assert back_dated.value.code == "PERIOD_DISTRIBUTED"

    # The P&L of the period is unchanged by the closing entries (D-29).
    assert reports.profit_and_loss(conn, start, end).net_profit == D("25000.00")

    reversed_ = distribution.reverse(conn, posted.document.id, "خطأ في الفترة", user_id=OWNER)
    assert reversed_.status == "REVERSED"
    assert (shop.current("A"), shop.current("B")) == (0, 0)
    assert shop.account("RETAINED_EARNINGS") == 0
    shop.expense(middle, "100")  # the period is open again


def test_the_next_period_starts_where_the_last_ended(fresh_tenant: tuple[Connection, uuid.UUID]) -> None:
    conn, _ = fresh_tenant
    start, middle, end = _days(conn)
    shop = _Showroom(conn, {"A": "50", "B": "50"}, start)
    shop.expense(start, "1000")
    with pytest.raises(AppError) as gap:
        distribution.preview(conn, DistributionIn(period_from=middle, period_to=end))
    assert gap.value.code == "DISTRIBUTION_PERIOD_GAP"
    distribution.post(conn, DistributionIn(period_from=start, period_to=middle), user_id=OWNER)
    with pytest.raises(AppError) as skipped:
        distribution.preview(conn, DistributionIn(period_from=end, period_to=end))
    assert skipped.value.code == "DISTRIBUTION_PERIOD_GAP"


def test_loss_is_charged_to_partners_or_carried_forward(fresh_tenant: tuple[Connection, uuid.UUID]) -> None:
    conn, _ = fresh_tenant
    start, middle, end = _days(conn)
    shop = _Showroom(conn, {"A": "50", "B": "50"}, start)
    shop.expense(start, "10000")
    shop.sell_car(end, "100000", "130000")

    # P-09, ALLOCATE_TO_PARTNERS (default): a loss debits the current accounts.
    _settings(conn, loss_handling="CARRY_FORWARD")
    loss = distribution.post(conn, DistributionIn(period_from=start, period_to=middle), user_id=OWNER).document
    assert (loss.net_profit, loss.distributed, loss.carried_out) == (D("-10000.00"), 0, D("-10000.00"))
    assert shop.account("RETAINED_EARNINGS") == D("10000.00")  # debit: the loss waits in 3300
    assert shop.current("A") == 0

    later = distribution.post(
        conn, DistributionIn(period_from=middle + timedelta(days=1), period_to=end), user_id=OWNER
    )
    assert (later.document.carried_in, later.document.distributed) == (D("-10000.00"), D("20000.00"))
    assert (shop.current("A"), shop.current("B")) == (D("10000.00"), D("10000.00"))
    assert shop.account("RETAINED_EARNINGS") == 0


def test_allocate_to_partners_charges_a_loss(fresh_tenant: tuple[Connection, uuid.UUID]) -> None:
    conn, _ = fresh_tenant
    start, _, end = _days(conn)
    shop = _Showroom(conn, {"A": "70", "B": "30"}, start)
    shop.expense(start, "1000")
    plan = distribution.post(conn, DistributionIn(period_from=start, period_to=end), user_id=OWNER).document
    assert plan.distributed == D("-1000.00")
    assert (shop.current("A"), shop.current("B")) == (D("-700.00"), D("-300.00"))


def test_day_weighted_shares_when_ownership_changes(fresh_tenant: tuple[Connection, uuid.UUID]) -> None:
    conn, _ = fresh_tenant
    start, _, _ = _days(conn)
    end = start + timedelta(days=9)  # ten days
    shop = _Showroom(conn, {"A": "50", "B": "50"}, start)
    shop.set_shares(start + timedelta(days=5), {"A": "30", "B": "70"})
    shop.sell_car(start + timedelta(days=2), "100000", "110000")  # profit 10,000 in the first half

    day_weighted = distribution.preview(conn, DistributionIn(period_from=start, period_to=end))
    assert {line.amount for line in day_weighted.lines} == {D("4000.00"), D("6000.00")}  # 40% / 60%

    _settings(conn, prorata_method="SUB_PERIOD_PROFIT")
    sub_period = distribution.preview(conn, DistributionIn(period_from=start, period_to=end))
    assert {line.amount for line in sub_period.lines} == {D("5000.00")}  # earned while 50/50


def test_per_car_policy_allocates_at_sale_and_nets_at_close(fresh_tenant: tuple[Connection, uuid.UUID]) -> None:
    conn, _ = fresh_tenant
    start, middle, end = _days(conn)
    _settings(conn, profit_policy="PER_CAR")
    shop = _Showroom(conn, {"A": "50", "B": "50"}, start)
    sold = shop.sell_car(middle, "100000", "120000")
    assert len(sold.journal_entries) == 3  # sale, cost, allocation (P-10)
    assert (shop.current("A"), shop.current("B")) == (D("10000.00"), D("10000.00"))
    assert shop.account("PROFIT_ALLOCATED_IN_ADVANCE") == D("20000.00")

    # A cancelled sale takes its allocation back.
    second = shop.sell_car(middle, "50000", "60000")
    sales.cancel_sale(
        conn,
        second.document.id,
        SaleCancelIn(reason="تجربة الإلغاء", cancel_date=middle),
        user_id=OWNER,
        with_profit=True,
    )
    assert shop.current("A") == D("10000.00")

    shop.expense(middle, "4000")
    plan = distribution.post(conn, DistributionIn(period_from=start, period_to=end), user_id=OWNER).document
    assert (plan.net_profit, plan.allocated_in_advance, plan.distributed) == (
        D("16000.00"),
        D("20000.00"),
        D("-4000.00"),
    )
    assert (shop.current("A"), shop.current("B")) == (D("8000.00"), D("8000.00"))
    assert shop.account("PROFIT_ALLOCATED_IN_ADVANCE") == 0
    assert shop.account("RETAINED_EARNINGS") == 0
