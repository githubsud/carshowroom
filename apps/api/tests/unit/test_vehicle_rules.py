"""Posting rules 6-9, 11, 12, 26, 30-32, 34, 35 and the approved candidates
P-02 (credit refund), P-03 (cancellation to a refund liability) and P-04
(expense on a sold car). Written before the endpoints; amounts follow the
worked examples in docs/ACCOUNTING.md §3."""

import uuid
from datetime import date
from decimal import Decimal

import pytest

from app.domain.ledger import Account, CashAccountRef, LedgerRuleError, Line
from app.services.posting import rules

D = date(2026, 10, 2)
V1 = uuid.uuid4()
V7 = uuid.uuid4()
KARIM = uuid.uuid4()
HASSAN = uuid.uuid4()
AHMED = uuid.uuid4()
GARAGE = uuid.uuid4()
CASH = CashAccountRef(cash_account_id=uuid.uuid4(), ledger_account_id=uuid.uuid4())
BANK = CashAccountRef(cash_account_id=uuid.uuid4(), ledger_account_id=uuid.uuid4())
UTILITIES = Account.by_id(uuid.uuid4())


def money(value: str) -> Decimal:
    return Decimal(value)


def cash(ref: CashAccountRef, debit: str = "0", credit: str = "0") -> Line:
    return Line(account=ref.account, debit=money(debit), credit=money(credit), cash_account_id=ref.cash_account_id)


def system(key: str, debit: str = "0", credit: str = "0", **ids: uuid.UUID | str) -> Line:
    memo = ids.pop("memo", None)
    return Line(
        account=Account.system(key),
        debit=money(debit),
        credit=money(credit),
        memo=memo if isinstance(memo, str) else None,
        **{k: v for k, v in ids.items() if isinstance(v, uuid.UUID)},
    )


# --- Purchase (rules 6, 7, 8) ------------------------------------------------------------------


def test_rule_6_paid_purchase() -> None:
    draft = rules.vehicle_purchase(
        entry_date=D,
        vehicle_id=V1,
        seller_id=KARIM,
        price=money("400000.00"),
        payments=[(BANK, money("400000.00"))],
        description="شراء",
        source_id=None,
    )
    assert draft.source_type == "VEHICLE_PURCHASE"
    assert draft.lines == (
        system("VEHICLE_INVENTORY", debit="400000.00", vehicle_id=V1),
        cash(BANK, credit="400000.00"),
    )


def test_rule_7_partly_deferred_purchase_owes_the_seller_for_that_car() -> None:
    draft = rules.vehicle_purchase(
        entry_date=D,
        vehicle_id=V1,
        seller_id=KARIM,
        price=money("500000.00"),
        payments=[(CASH, money("300000.00"))],
        description="شراء",
        source_id=None,
    )
    assert draft.lines == (
        system("VEHICLE_INVENTORY", debit="500000.00", vehicle_id=V1),
        cash(CASH, credit="300000.00"),
        system("SELLER_PAYABLE", credit="200000.00", customer_id=KARIM, vehicle_id=V1),
    )


def test_purchase_payments_cannot_exceed_the_price() -> None:
    with pytest.raises(LedgerRuleError):
        rules.vehicle_purchase(
            entry_date=D,
            vehicle_id=V1,
            seller_id=KARIM,
            price=money("100.00"),
            payments=[(CASH, money("150.00"))],
            description="x",
            source_id=None,
        )


def test_rule_8_pay_seller_later() -> None:
    draft = rules.seller_payment(
        entry_date=D,
        vehicle_id=V1,
        seller_id=KARIM,
        amount=money("200000.00"),
        paid_from=BANK,
        description="سداد",
        source_id=None,
    )
    assert draft.source_type == "SELLER_PAYMENT"
    assert draft.lines == (
        system("SELLER_PAYABLE", debit="200000.00", customer_id=KARIM, vehicle_id=V1),
        cash(BANK, credit="200000.00"),
    )


# --- Vehicle expenses (rules 9, 30, 31; P-04) ---------------------------------------------------------


def test_rule_9_expense_is_capitalized_with_the_category_as_memo() -> None:
    draft = rules.vehicle_expense(
        entry_date=D,
        vehicle_id=V1,
        amount=money("15000.00"),
        category_label="دهان",
        sold=False,
        funding=rules.CashFunding(CASH),
        description="دهان",
        source_id=None,
    )
    assert draft.source_type == "VEHICLE_EXPENSE"
    assert draft.lines == (
        system("VEHICLE_INVENTORY", debit="15000.00", vehicle_id=V1, memo="دهان"),
        cash(CASH, credit="15000.00"),
    )


def test_p04_expense_on_a_sold_car_goes_to_cost_of_sales() -> None:
    draft = rules.vehicle_expense(
        entry_date=D,
        vehicle_id=V1,
        amount=money("1200.00"),
        category_label="نقل",
        sold=True,
        funding=rules.CashFunding(CASH),
        description="نقل",
        source_id=None,
    )
    assert draft.lines[0] == system("COST_OF_VEHICLES_SOLD", debit="1200.00", vehicle_id=V1, memo="نقل")


@pytest.mark.parametrize(("mode", "key"), [("CURRENT_ACCOUNT", "PARTNER_CURRENT"), ("LOAN", "PARTNER_LOANS_PAYABLE")])
def test_rule_30_partner_pays_a_car_expense(mode: str, key: str) -> None:
    draft = rules.vehicle_expense(
        entry_date=D,
        vehicle_id=V7,
        amount=money("3000.00"),
        category_label="نقل",
        sold=False,
        funding=rules.PartnerFunding(partner_id=AHMED, mode=mode),  # type: ignore[arg-type]
        description="نقل",
        source_id=None,
    )
    assert draft.lines == (
        system("VEHICLE_INVENTORY", debit="3000.00", vehicle_id=V7, memo="نقل"),
        system(key, credit="3000.00", partner_id=AHMED),
    )
    assert draft.cash_effects() == {}


def test_rule_31_car_expense_on_supplier_credit() -> None:
    draft = rules.vehicle_expense(
        entry_date=D,
        vehicle_id=V7,
        amount=money("12000.00"),
        category_label="صيانة",
        sold=False,
        funding=rules.SupplierFunding(GARAGE),
        description="صيانة",
        source_id=None,
    )
    assert draft.lines == (
        system("VEHICLE_INVENTORY", debit="12000.00", vehicle_id=V7, memo="صيانة"),
        system("SUPPLIER_PAYABLE", credit="12000.00", supplier_id=GARAGE),
    )


def test_rule_31_general_expense_on_supplier_credit() -> None:
    draft = rules.general_expense_on_credit(
        entry_date=D,
        amount=money("900.00"),
        expense_account=UTILITIES,
        supplier_id=GARAGE,
        description="كهرباء",
        source_id=None,
    )
    assert draft.source_type == "GENERAL_EXPENSE"
    assert draft.lines == (
        Line(account=UTILITIES, debit=money("900.00")),
        system("SUPPLIER_PAYABLE", credit="900.00", supplier_id=GARAGE),
    )


def test_rule_32_pay_supplier() -> None:
    draft = rules.supplier_payment(
        entry_date=D, supplier_id=GARAGE, amount=money("12000.00"), paid_from=CASH, description="x", source_id=None
    )
    assert draft.source_type == "SUPPLIER_PAYMENT"
    assert draft.lines == (
        system("SUPPLIER_PAYABLE", debit="12000.00", supplier_id=GARAGE),
        cash(CASH, credit="12000.00"),
    )


# --- Deposits (rules 11, 34, 35) -------------------------------------------------------------------


def test_rule_11_deposit_received() -> None:
    draft = rules.deposit_received(
        entry_date=D,
        customer_id=HASSAN,
        vehicle_id=V1,
        amount=money("20000.00"),
        received_in=CASH,
        description="عربون",
        source_id=None,
    )
    assert draft.source_type == "DEPOSIT"
    assert draft.lines == (
        cash(CASH, debit="20000.00"),
        system("CUSTOMER_DEPOSITS", credit="20000.00", customer_id=HASSAN, vehicle_id=V1),
    )


def test_rule_34_deposit_refunded() -> None:
    draft = rules.deposit_refunded(
        entry_date=D,
        customer_id=HASSAN,
        vehicle_id=V1,
        amount=money("20000.00"),
        paid_from=CASH,
        description="رد",
        source_id=None,
    )
    assert draft.source_type == "DEPOSIT_REFUND"
    assert draft.lines == (
        system("CUSTOMER_DEPOSITS", debit="20000.00", customer_id=HASSAN, vehicle_id=V1),
        cash(CASH, credit="20000.00"),
    )


def test_rule_35_deposit_forfeited_is_other_income() -> None:
    draft = rules.deposit_forfeited(
        entry_date=D, customer_id=HASSAN, vehicle_id=V1, amount=money("20000.00"), description="x", source_id=None
    )
    assert draft.source_type == "DEPOSIT_FORFEIT"
    assert draft.lines == (
        system("CUSTOMER_DEPOSITS", debit="20000.00", customer_id=HASSAN, vehicle_id=V1),
        system("OTHER_INCOME", credit="20000.00"),
    )
    assert draft.cash_effects() == {}


# --- Sales (rules 12, 26) -----------------------------------------------------------------------------


def test_rule_12_cash_sale_with_deposit_applied() -> None:
    draft = rules.sale(
        entry_date=D,
        vehicle_id=V1,
        buyer_id=HASSAN,
        sale_price=money("480000.00"),
        payments=[(BANK, money("460000.00"))],
        deposit_applied=money("20000.00"),
        trade_in=None,
        description="بيع",
        source_id=None,
    )
    assert draft.source_type == "SALE"
    assert draft.lines == (
        cash(BANK, debit="460000.00"),
        system("CUSTOMER_DEPOSITS", debit="20000.00", customer_id=HASSAN, vehicle_id=V1),
        system("VEHICLE_SALES", credit="480000.00", vehicle_id=V1),
    )


def test_rule_12_cost_recognition_uses_the_vehicle_cost() -> None:
    draft = rules.cost_of_sale(
        entry_date=D, vehicle_id=V1, cost=money("415000.00"), description="تكلفة", source_id=None
    )
    assert draft.source_type == "SALE_COST"
    assert draft.lines == (
        system("COST_OF_VEHICLES_SOLD", debit="415000.00", vehicle_id=V1),
        system("VEHICLE_INVENTORY", credit="415000.00", vehicle_id=V1),
    )


def test_rule_26_trade_in_enters_inventory_at_the_agreed_value() -> None:
    draft = rules.sale(
        entry_date=D,
        vehicle_id=V1,
        buyer_id=HASSAN,
        sale_price=money("550000.00"),
        payments=[(BANK, money("350000.00"))],
        deposit_applied=money("0"),
        trade_in=(V7, money("200000.00")),
        description="بيع مع استبدال",
        source_id=None,
    )
    assert draft.lines == (
        cash(BANK, debit="350000.00"),
        system("VEHICLE_INVENTORY", debit="200000.00", vehicle_id=V7),
        system("VEHICLE_SALES", credit="550000.00", vehicle_id=V1),
    )


def test_mixed_payment_legs_each_hit_their_account() -> None:
    draft = rules.sale(
        entry_date=D,
        vehicle_id=V1,
        buyer_id=HASSAN,
        sale_price=money("300000.00"),
        payments=[(CASH, money("100000.00")), (BANK, money("200000.00"))],
        deposit_applied=money("0"),
        trade_in=None,
        description="x",
        source_id=None,
    )
    assert draft.cash_effects() == {CASH.cash_account_id: money("100000.00"), BANK.cash_account_id: money("200000.00")}


def test_sale_amounts_must_add_up_to_the_price() -> None:
    with pytest.raises(LedgerRuleError):
        rules.sale(
            entry_date=D,
            vehicle_id=V1,
            buyer_id=HASSAN,
            sale_price=money("300000.00"),
            payments=[(CASH, money("100000.00"))],
            deposit_applied=money("0"),
            trade_in=None,
            description="x",
            source_id=None,
        )


def test_a_car_cannot_be_its_own_trade_in() -> None:
    with pytest.raises(LedgerRuleError):
        rules.sale(
            entry_date=D,
            vehicle_id=V1,
            buyer_id=HASSAN,
            sale_price=money("100.00"),
            payments=[],
            deposit_applied=money("0"),
            trade_in=(V1, money("100.00")),
            description="x",
            source_id=None,
        )


def test_cost_must_be_positive() -> None:
    with pytest.raises(LedgerRuleError):
        rules.cost_of_sale(entry_date=D, vehicle_id=V1, cost=money("0"), description="x", source_id=None)


# --- Cancellation (P-03, D-41) and credit refunds (P-02) --------------------------------------------------


def test_p03_cancellation_moves_what_the_customer_paid_to_a_refund_liability() -> None:
    draft = rules.sale_cancellation_to_credit(
        entry_date=D,
        vehicle_id=V1,
        buyer_id=HASSAN,
        sale_price=money("550000.00"),
        amount_paid=money("350000.00"),
        trade_in=(V7, money("200000.00")),
        description="إلغاء",
        source_id=None,
    )
    assert draft.source_type == "SALE_CANCELLATION"
    assert draft.lines == (
        system("VEHICLE_SALES", debit="550000.00", vehicle_id=V1),
        system("CUSTOMER_CREDITS", credit="350000.00", customer_id=HASSAN),
        system("VEHICLE_INVENTORY", credit="200000.00", vehicle_id=V7),
    )
    # No money moves until the refund is actually paid (C-06).
    assert draft.cash_effects() == {}


def test_p02_refund_of_customer_credit() -> None:
    draft = rules.customer_credit_refund(
        entry_date=D, customer_id=HASSAN, amount=money("350000.00"), paid_from=BANK, description="رد", source_id=None
    )
    assert draft.source_type == "CUSTOMER_REFUND"
    assert draft.lines == (
        system("CUSTOMER_CREDITS", debit="350000.00", customer_id=HASSAN),
        cash(BANK, credit="350000.00"),
    )
