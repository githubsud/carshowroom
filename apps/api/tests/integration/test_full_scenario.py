"""Phase 7 acceptance (FACT): the full end-to-end scenario of SPEC §7 /
ACCOUNTING §4 matches the hand-calculated values exactly.

It runs in a brand-new showroom inside one transaction that is rolled back, so
every balance starts at zero and nothing is left behind. The services are the
same ones the API calls."""

import uuid
from datetime import timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import Connection, text

from app.domain.consignment import ConsignOutIn, ExternalSaleIn, ExternalShowroomIn
from app.domain.distribution import DistributionIn
from app.domain.finance import CashAccountIn, TransferIn
from app.domain.installments import ReceiptIn
from app.domain.partners import PartnerIn, PartnerTransactionIn, ShareChangeIn
from app.domain.sales import SaleDraftIn
from app.domain.vehicles import CustomerIn, PurchaseIn, VehicleExpenseIn, VehicleIn
from app.services import consignment, customers, distribution, finance, installments, partners, reports, sales, vehicles
from tests.integration.test_vehicles_sales import OWNER_ID, _NoCipher

D = Decimal


def _balance(conn: Connection, key: str, **ids: uuid.UUID) -> Decimal:
    filters = "".join(f" and l.{column} = :{column}" for column in ids)
    value = conn.execute(
        text(
            "select coalesce(sum(l.debit - l.credit), 0) from public.journal_lines l "  # noqa: S608 - fixed columns
            "join public.ledger_accounts a on a.id = l.ledger_account_id where a.system_key = :key" + filters
        ),
        {"key": key, **ids},
    ).scalar_one()
    return D(value)


def _type_total(conn: Connection, account_type: str) -> Decimal:
    value = conn.execute(
        text(
            "select coalesce(sum(l.debit - l.credit), 0) from public.journal_lines l "
            "join public.ledger_accounts a on a.id = l.ledger_account_id where a.type = :t"
        ),
        {"t": account_type},
    ).scalar_one()
    return D(value)


def _buy(conn: Connection, model: str, price: str, seller: uuid.UUID, bank: uuid.UUID, day: Any) -> uuid.UUID:
    car = vehicles.create_vehicle(conn, VehicleIn(make="Toyota", model=model, year=2020))
    vehicles.record_purchase(
        conn,
        car,
        PurchaseIn.model_validate(
            {
                "seller_customer_id": seller,
                "purchase_date": day,
                "price": price,
                "payments": [{"cash_account_id": bank, "amount": price}],
                "ready_for_sale": True,
            }
        ),
    )
    return car


def _sell(
    conn: Connection, car: uuid.UUID, buyer: uuid.UUID, price: str, payments: list[dict[str, Any]], **extra: Any
) -> Any:
    draft = sales.create_draft(
        conn,
        SaleDraftIn.model_validate(
            {
                "vehicle_id": car,
                "buyer_customer_id": buyer,
                "sale_date": extra.pop("day"),
                "list_price": price,
                "payments": payments,
                **extra,
            }
        ),
        viewer_id=OWNER_ID,
        see_all_drafts=True,
        with_profit=True,
    )
    return sales.post_sale(conn, draft.id, user_id=OWNER_ID, with_profit=True).document


def test_full_scenario_matches_the_hand_calculation(fresh_tenant: tuple[Connection, uuid.UUID]) -> None:
    conn, _ = fresh_tenant
    day = finance.tenant_info(conn).today - timedelta(days=1)

    cash = finance.create_cash_account(conn, CashAccountIn(kind="CASH_BOX", name_ar="الخزنة", is_default=True)).id
    bank = finance.create_cash_account(conn, CashAccountIn(kind="BANK", name_ar="بنك", bank_name="CIB")).id

    # Partners A 50%, B 30%, C 20%; step 1: capital into the bank (rule 1).
    names = {"A": "أحمد", "B": "منى", "C": "يوسف"}
    ids = {key: partners.create_partner(conn, PartnerIn(name_ar=name), _NoCipher()).id for key, name in names.items()}  # type: ignore[arg-type]
    partners.change_shares(
        conn,
        ShareChangeIn.model_validate(
            {
                "effective_from": day,
                "shares": [
                    {"partner_id": ids["A"], "percentage": "50"},
                    {"partner_id": ids["B"], "percentage": "30"},
                    {"partner_id": ids["C"], "percentage": "20"},
                ],
            }
        ),
    )

    def partner_txn(key: str, kind: str, amount: str, account: uuid.UUID) -> None:
        partners.record_transaction(
            conn,
            ids[key],
            PartnerTransactionIn.model_validate(
                {"type": kind, "txn_date": day, "amount": amount, "cash_account_id": account}
            ),
        )

    for key, amount in (("A", "1000000"), ("B", "600000"), ("C", "400000")):
        partner_txn(key, "CONTRIBUTION", amount, bank)

    # Step 2: buy three cars from the bank (rule 6).
    seller = customers.create_customer(conn, CustomerIn(name="بائع"), _NoCipher()).id  # type: ignore[arg-type]
    car1 = _buy(conn, "Corolla", "400000", seller, bank, day)
    car2 = _buy(conn, "Camry", "500000", seller, bank, day)
    car3 = _buy(conn, "Yaris", "300000", seller, bank, day)

    # Step 3: transfer 100,000 bank -> cash (rule 21).
    finance.record_transfer(
        conn,
        TransferIn(transfer_date=day, from_cash_account_id=bank, to_cash_account_id=cash, amount=D("100000")),
    )

    # Step 4: expenses in cash (rule 9).
    category = conn.execute(
        text("select id from public.expense_categories where kind = 'VEHICLE' and code = 'maintenance'")
    ).scalar_one()
    for car, amount in ((car1, "10000"), (car2, "20000"), (car3, "5000")):
        vehicles.record_expense(
            conn,
            car,
            VehicleExpenseIn.model_validate(
                {"expense_date": day, "category_id": category, "amount": amount, "cash_account_id": cash}
            ),
        )

    # Step 5: Car1 sold for cash at 480,000 (rule 12).
    buyer1 = customers.create_customer(conn, CustomerIn(name="مشتري ١"), _NoCipher()).id  # type: ignore[arg-type]
    sale1 = _sell(conn, car1, buyer1, "480000", [{"cash_account_id": cash, "amount": "480000"}], day=day)
    assert sale1.profit.gross_profit == D("70000.00")

    # Step 6: Car2 on installments, 160,000 down + 6 x 80,000 (rule 13).
    buyer2 = customers.create_customer(conn, CustomerIn(name="مشتري ٢"), _NoCipher()).id  # type: ignore[arg-type]
    sale2 = _sell(
        conn,
        car2,
        buyer2,
        "640000",
        [{"cash_account_id": cash, "amount": "160000"}],
        day=day,
        installments={"frequency": "MONTHLY", "count": 6, "first_due_date": day + timedelta(days=30)},
    )
    assert sale2.profit.gross_profit == D("120000.00")

    # Step 7: Car3 consigned out and sold there at 360,000, commission 10,000 (rule 18).
    showroom = consignment.create_showroom(conn, ExternalShowroomIn(name="معرض خارجي"))
    out = consignment.consign_out(
        conn,
        ConsignOutIn.model_validate(
            {
                "vehicle_id": car3,
                "external_showroom_id": showroom.id,
                "sent_date": day,
                "commission_type": "FIXED",
                "commission_value": "10000",
            }
        ),
    )
    consignment.record_external_sale(
        conn, out.id, ExternalSaleIn.model_validate({"sale_date": day, "sale_price": "360000"}), user_id=OWNER_ID
    )

    # Step 8: two installments collected in cash (rule 15).
    assert sale2.plan_id is not None
    installments.record_receipt(
        conn,
        sale2.plan_id,
        ReceiptIn.model_validate({"receipt_date": day, "amount": "160000", "cash_account_id": cash}),
    )

    # Steps 9-10: B draws 20,000 (rule 3); loan of 30,000 to C (rule 4).
    partner_txn("B", "DRAWING", "20000", cash)
    partner_txn("C", "LOAN_TO_PARTNER", "30000", cash)

    # P&L before closing.
    pnl = reports.profit_and_loss(conn, day, day)
    assert (pnl.revenue_total, pnl.cost_of_sales, pnl.gross_profit) == (
        D("1480000.00"),
        D("1235000.00"),
        D("245000.00"),
    )
    assert (pnl.expenses_total, pnl.net_profit) == (D("10000.00"), D("235000.00"))

    # Steps 11-12: close the period and distribute (rules 23, 22).
    payload = DistributionIn(period_from=day, period_to=day)
    preview = distribution.preview(conn, payload)
    assert preview.net_profit == D("235000.00")
    assert {line.partner_id: line.amount for line in preview.lines} == {
        ids["A"]: D("117500.00"),
        ids["B"]: D("70500.00"),
        ids["C"]: D("47000.00"),
    }
    posted = distribution.post(conn, payload, user_id=OWNER_ID).document
    assert [line.amount for line in posted.lines] == [line.amount for line in preview.lines]  # preview = post

    # Expected balances after step 12 (ACCOUNTING §4).
    assert finance.get_cash_account(conn, cash).balance == D("815000.00")
    assert finance.get_cash_account(conn, bank).balance == D("700000.00")
    assert _balance(conn, "VEHICLE_INVENTORY") == 0
    assert _balance(conn, "INSTALLMENT_RECEIVABLE", customer_id=buyer2) == D("320000.00")
    assert _balance(conn, "EXTERNAL_SHOWROOM_RECEIVABLE", external_showroom_id=showroom.id) == D("350000.00")
    assert _balance(conn, "PARTNER_LOANS_RECEIVABLE", partner_id=ids["C"]) == D("30000.00")
    assert _type_total(conn, "ASSET") == D("2215000.00")
    assert _type_total(conn, "LIABILITY") == 0
    capital = {k: -_balance(conn, "PARTNER_CAPITAL", partner_id=v) for k, v in ids.items()}
    current = {k: -_balance(conn, "PARTNER_CURRENT", partner_id=v) for k, v in ids.items()}
    assert capital == {"A": D("1000000.00"), "B": D("600000.00"), "C": D("400000.00")}
    assert current == {"A": D("117500.00"), "B": D("50500.00"), "C": D("47000.00")}
    assert _balance(conn, "RETAINED_EARNINGS") == 0
    assert -_type_total(conn, "EQUITY") == D("2215000.00")
    assert _type_total(conn, "INCOME") == 0  # all closed
    assert _type_total(conn, "EXPENSE") == 0

    # The P&L still shows the period's activity (closing entries are excluded, D-29).
    assert reports.profit_and_loss(conn, day, day).net_profit == D("235000.00")
    check = reports.balance_check(conn, day)
    assert check.balanced
    assert check.assets == D("2215000.00")

    # Partner net position (Q-17 default).
    summary = partners.summary(conn, day)
    net = {row.partner_id: row.net for row in summary.rows}
    assert (net[ids["A"]], net[ids["B"]], net[ids["C"]]) == (D("1117500.00"), D("650500.00"), D("417000.00"))
