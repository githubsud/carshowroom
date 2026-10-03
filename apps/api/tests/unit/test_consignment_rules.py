"""Consignment posting rules 10, 16, 17, 18, 19 and the approved candidates
P-05 (showroom-borne expense) and P-06 (consignor reimburses), with the
commission terms of SPEC §4.4. Written before the endpoints; amounts follow
the worked examples in docs/ACCOUNTING.md §3 (V3 owned by Samir, V4 at
Al-Amal Motors)."""

import uuid
from datetime import date
from decimal import Decimal

import pytest

from app.domain.consignment import CommissionError, commission_for, external_commission_for, owner_share
from app.domain.ledger import Account, CashAccountRef, LedgerRuleError, Line
from app.services.posting import rules

D = date(2026, 10, 7)
V3 = uuid.uuid4()
V4 = uuid.uuid4()
SAMIR = uuid.uuid4()
BUYER = uuid.uuid4()
AL_AMAL = uuid.uuid4()
GARAGE = uuid.uuid4()
AHMED = uuid.uuid4()
CASH = CashAccountRef(cash_account_id=uuid.uuid4(), ledger_account_id=uuid.uuid4())
BANK = CashAccountRef(cash_account_id=uuid.uuid4(), ledger_account_id=uuid.uuid4())


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


# --- Commission terms (SPEC §4.4, Q-15) --------------------------------------------------------------


def test_percentage_commission_of_the_worked_example() -> None:
    assert commission_for("COMMISSION_PCT", money("300000.00"), net_price=None, value=money("5")) == money("15000.00")


def test_percentage_commission_rounds_half_up_to_the_cent() -> None:
    assert commission_for("COMMISSION_PCT", money("100.10"), net_price=None, value=money("2.5")) == money("2.50")
    assert commission_for("COMMISSION_PCT", money("100.30"), net_price=None, value=money("2.5")) == money("2.51")


def test_fixed_commission_is_the_agreed_amount() -> None:
    assert commission_for("COMMISSION_FIXED", money("300000.00"), net_price=None, value=money("12000")) == money(
        "12000.00"
    )


def test_net_price_commission_is_the_difference() -> None:
    assert commission_for("NET_PRICE", money("300000.00"), net_price=money("280000"), value=None) == money("20000.00")


def test_sale_at_or_below_the_net_price_is_blocked() -> None:
    # Q-15 default: a sale below the agreed net is not allowed; at the net the showroom earns nothing.
    with pytest.raises(CommissionError) as below:
        commission_for("NET_PRICE", money("270000.00"), net_price=money("280000"), value=None)
    assert below.value.code == "SALE_BELOW_NET_PRICE"
    with pytest.raises(CommissionError):
        commission_for("NET_PRICE", money("280000.00"), net_price=money("280000"), value=None)


def test_fixed_commission_cannot_eat_the_whole_price() -> None:
    with pytest.raises(CommissionError) as error:
        commission_for("COMMISSION_FIXED", money("10000.00"), net_price=None, value=money("10000"))
    assert error.value.code == "COMMISSION_EXCEEDS_PRICE"


def test_external_commission_fixed_and_percentage() -> None:
    assert external_commission_for("FIXED", money("400000.00"), money("8000")) == money("8000.00")
    assert external_commission_for("PCT", money("400000.00"), money("2")) == money("8000.00")
    with pytest.raises(CommissionError):
        external_commission_for("FIXED", money("8000.00"), money("8000"))


def test_owner_share_of_a_shared_expense() -> None:
    assert owner_share(money("2000.00"), "OWNER", None) == money("2000.00")
    assert owner_share(money("2000.00"), "SHOWROOM", None) == money("0")
    assert owner_share(money("2000.00"), "SHARED", money("50")) == money("1000.00")
    assert owner_share(money("1000.01"), "SHARED", money("50")) == money("500.01")


# --- Rule 10 / P-05 / C-11: expenses on a consigned-in car ------------------------------------------


def test_rule_10_owner_borne_expense_is_recoverable() -> None:
    draft = rules.consigned_vehicle_expense(
        entry_date=D,
        vehicle_id=V3,
        consignor_id=SAMIR,
        amount=money("2000.00"),
        owner_part=money("2000.00"),
        category_label="تنظيف",
        funding=rules.CashFunding(CASH),
        description="تنظيف",
        source_id=None,
    )
    assert draft.source_type == "VEHICLE_EXPENSE"
    assert draft.lines == (
        system("CONSIGNOR_RECOVERABLE", debit="2000.00", consignor_id=SAMIR, vehicle_id=V3, memo="تنظيف"),
        cash(CASH, credit="2000.00"),
    )


def test_p05_showroom_borne_expense_goes_to_the_showroom_expense_account() -> None:
    draft = rules.consigned_vehicle_expense(
        entry_date=D,
        vehicle_id=V3,
        consignor_id=SAMIR,
        amount=money("2000.00"),
        owner_part=money("0"),
        category_label="تنظيف",
        funding=rules.CashFunding(CASH),
        description="تنظيف",
        source_id=None,
    )
    assert draft.lines == (
        system("EXP_CONSIGNMENT", debit="2000.00", vehicle_id=V3, memo="تنظيف"),
        cash(CASH, credit="2000.00"),
    )


def test_p05_shared_expense_is_split() -> None:
    draft = rules.consigned_vehicle_expense(
        entry_date=D,
        vehicle_id=V3,
        consignor_id=SAMIR,
        amount=money("2000.00"),
        owner_part=money("1200.00"),
        category_label="صيانة",
        funding=rules.CashFunding(BANK),
        description="صيانة",
        source_id=None,
    )
    assert draft.lines == (
        system("CONSIGNOR_RECOVERABLE", debit="1200.00", consignor_id=SAMIR, vehicle_id=V3, memo="صيانة"),
        system("EXP_CONSIGNMENT", debit="800.00", vehicle_id=V3, memo="صيانة"),
        cash(BANK, credit="2000.00"),
    )


def test_c11_partner_and_supplier_funding_on_a_consigned_car_debit_1430_not_inventory() -> None:
    by_partner = rules.consigned_vehicle_expense(
        entry_date=D,
        vehicle_id=V3,
        consignor_id=SAMIR,
        amount=money("3000.00"),
        owner_part=money("3000.00"),
        category_label="صيانة",
        funding=rules.PartnerFunding(AHMED, "CURRENT_ACCOUNT"),
        description="صيانة",
        source_id=None,
    )
    assert by_partner.lines == (
        system("CONSIGNOR_RECOVERABLE", debit="3000.00", consignor_id=SAMIR, vehicle_id=V3, memo="صيانة"),
        system("PARTNER_CURRENT", credit="3000.00", partner_id=AHMED),
    )
    on_credit = rules.consigned_vehicle_expense(
        entry_date=D,
        vehicle_id=V3,
        consignor_id=SAMIR,
        amount=money("12000.00"),
        owner_part=money("12000.00"),
        category_label="صيانة",
        funding=rules.SupplierFunding(GARAGE),
        description="صيانة",
        source_id=None,
    )
    assert on_credit.lines[1] == system("SUPPLIER_PAYABLE", credit="12000.00", supplier_id=GARAGE)


def test_owner_part_cannot_exceed_the_expense() -> None:
    with pytest.raises(LedgerRuleError):
        rules.consigned_vehicle_expense(
            entry_date=D,
            vehicle_id=V3,
            consignor_id=SAMIR,
            amount=money("100.00"),
            owner_part=money("100.01"),
            category_label="x",
            funding=rules.CashFunding(CASH),
            description="x",
            source_id=None,
        )


# --- Rule 16: sale of a consigned-in car -------------------------------------------------------------


def test_rule_16_entry_a_full_price_is_owed_to_the_consignor() -> None:
    draft = rules.sale(
        entry_date=D,
        vehicle_id=V3,
        buyer_id=BUYER,
        sale_price=money("300000.00"),
        payments=[(BANK, money("300000.00"))],
        deposit_applied=money("0"),
        trade_in=None,
        description="بيع أمانة",
        source_id=None,
        consignor_id=SAMIR,
    )
    assert draft.source_type == "SALE"
    assert draft.lines == (
        cash(BANK, debit="300000.00"),
        system("CONSIGNOR_PAYABLE", credit="300000.00", consignor_id=SAMIR, vehicle_id=V3),
    )


def test_rule_16_with_a_deposit_applied() -> None:
    draft = rules.sale(
        entry_date=D,
        vehicle_id=V3,
        buyer_id=BUYER,
        sale_price=money("300000.00"),
        payments=[(BANK, money("290000.00"))],
        deposit_applied=money("10000.00"),
        trade_in=None,
        description="بيع أمانة",
        source_id=None,
        consignor_id=SAMIR,
    )
    assert draft.lines == (
        cash(BANK, debit="290000.00"),
        system("CUSTOMER_DEPOSITS", debit="10000.00", customer_id=BUYER, vehicle_id=V3),
        system("CONSIGNOR_PAYABLE", credit="300000.00", consignor_id=SAMIR, vehicle_id=V3),
    )


def test_p14_a_consigned_car_is_not_sold_on_installments() -> None:
    with pytest.raises(LedgerRuleError):
        rules.sale(
            entry_date=D,
            vehicle_id=V3,
            buyer_id=BUYER,
            sale_price=money("300000.00"),
            payments=[(BANK, money("100000.00"))],
            deposit_applied=money("0"),
            trade_in=None,
            description="x",
            source_id=None,
            financed=money("200000.00"),
            consignor_id=SAMIR,
        )


def test_rule_16_entry_b_commission_and_recovery() -> None:
    draft = rules.consignment_commission(
        entry_date=D,
        vehicle_id=V3,
        consignor_id=SAMIR,
        commission=money("15000.00"),
        recovered=money("2000.00"),
        description="عمولة",
        source_id=None,
    )
    assert draft.source_type == "CONSIGNMENT_COMMISSION"
    assert draft.lines == (
        system("CONSIGNOR_PAYABLE", debit="17000.00", consignor_id=SAMIR, vehicle_id=V3),
        system("CONSIGNMENT_COMMISSION", credit="15000.00", vehicle_id=V3),
        system("CONSIGNOR_RECOVERABLE", credit="2000.00", consignor_id=SAMIR, vehicle_id=V3),
    )
    owed = money("300000.00") - draft.lines[0].debit
    assert owed == money("283000.00")


def test_rule_16_entry_b_without_recoverable_expenses() -> None:
    draft = rules.consignment_commission(
        entry_date=D,
        vehicle_id=V3,
        consignor_id=SAMIR,
        commission=money("20000.00"),
        recovered=money("0"),
        description="عمولة",
        source_id=None,
    )
    assert draft.lines == (
        system("CONSIGNOR_PAYABLE", debit="20000.00", consignor_id=SAMIR, vehicle_id=V3),
        system("CONSIGNMENT_COMMISSION", credit="20000.00", vehicle_id=V3),
    )


# --- Rule 17 and P-06: settling with the owner -----------------------------------------------------------


def test_rule_17_pay_the_consignor() -> None:
    draft = rules.consignor_payout(
        entry_date=D,
        vehicle_id=V3,
        consignor_id=SAMIR,
        amount=money("283000.00"),
        paid_from=BANK,
        description="تسوية",
        source_id=None,
    )
    assert draft.source_type == "CONSIGNOR_PAYOUT"
    assert draft.lines == (
        system("CONSIGNOR_PAYABLE", debit="283000.00", consignor_id=SAMIR, vehicle_id=V3),
        cash(BANK, credit="283000.00"),
    )


def test_p06_consignor_reimburses_recoverable_expenses() -> None:
    draft = rules.consignor_recovery(
        entry_date=D,
        vehicle_id=V3,
        consignor_id=SAMIR,
        amount=money("2000.00"),
        received_in=CASH,
        description="استرداد",
        source_id=None,
    )
    assert draft.source_type == "CONSIGNOR_RECOVERY"
    assert draft.lines == (
        cash(CASH, debit="2000.00"),
        system("CONSIGNOR_RECOVERABLE", credit="2000.00", consignor_id=SAMIR, vehicle_id=V3),
    )


# --- Rules 18 and 19: our car sold by an external showroom ---------------------------------------------


def test_rule_18_three_entries() -> None:
    sale_entry = rules.external_sale(
        entry_date=D,
        vehicle_id=V4,
        external_showroom_id=AL_AMAL,
        sale_price=money("400000.00"),
        description="بيع عن طريق معرض",
        source_id=None,
    )
    assert sale_entry.source_type == "SALE"
    assert sale_entry.lines == (
        system("EXTERNAL_SHOWROOM_RECEIVABLE", debit="400000.00", external_showroom_id=AL_AMAL, vehicle_id=V4),
        system("VEHICLE_SALES", credit="400000.00", vehicle_id=V4),
    )
    commission = rules.external_commission(
        entry_date=D,
        vehicle_id=V4,
        external_showroom_id=AL_AMAL,
        commission=money("8000.00"),
        description="عمولة المعرض",
        source_id=None,
    )
    assert commission.source_type == "EXTERNAL_COMMISSION"
    assert commission.lines == (
        system("EXTERNAL_COMMISSION_EXPENSE", debit="8000.00", external_showroom_id=AL_AMAL, vehicle_id=V4),
        system("EXTERNAL_SHOWROOM_RECEIVABLE", credit="8000.00", external_showroom_id=AL_AMAL, vehicle_id=V4),
    )
    cost = rules.cost_of_sale(entry_date=D, vehicle_id=V4, cost=money("350000.00"), description="تكلفة", source_id=None)
    assert cost.lines == (
        system("COST_OF_VEHICLES_SOLD", debit="350000.00", vehicle_id=V4),
        system("VEHICLE_INVENTORY", credit="350000.00", vehicle_id=V4),
    )
    receivable = sale_entry.lines[0].debit - commission.lines[1].credit
    assert receivable == money("392000.00")
    # Q-34 default: profit after the external commission.
    assert sale_entry.lines[1].credit - cost.lines[0].debit - commission.lines[0].debit == money("42000.00")


def test_rule_19_collect_from_the_external_showroom() -> None:
    draft = rules.external_collection(
        entry_date=D,
        external_showroom_id=AL_AMAL,
        amount=money("392000.00"),
        received_in=BANK,
        description="تحصيل",
        source_id=None,
    )
    assert draft.source_type == "EXTERNAL_COLLECTION"
    assert draft.lines == (
        cash(BANK, debit="392000.00"),
        system("EXTERNAL_SHOWROOM_RECEIVABLE", credit="392000.00", external_showroom_id=AL_AMAL),
    )


@pytest.mark.parametrize("amount", ["0", "-1.00", "10.001"])
def test_amounts_must_be_positive_with_two_decimals(amount: str) -> None:
    with pytest.raises(LedgerRuleError):
        rules.external_collection(
            entry_date=D,
            external_showroom_id=AL_AMAL,
            amount=money(amount),
            received_in=BANK,
            description="x",
            source_id=None,
        )
