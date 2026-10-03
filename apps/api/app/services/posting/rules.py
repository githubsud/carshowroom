"""Posting rules (docs/ACCOUNTING.md §3). Pure functions: command in, balanced
draft out. Unit-tested in tests/unit/test_posting_rules.py.

Implemented: 1-5, 28, 29 (partners), 6-9 (purchase, seller payment, vehicle
expense), 11, 34, 35 (deposits), 12, 13, 26 (sale, installment sale mode a,
trade-in, cost recognition), 15 and 27 (installment collected, cheque bounced),
20, 21 (general expense, transfer), 24 (reversal; the database performs it,
this mirror is used for previews and cash checks), 30-32 (partner-paid and
supplier-credit expenses, supplier payment), 10 and 16-19 (consignment in
and out), and the approved candidates P-01 to P-07. Further rules arrive
with their phases (BACKLOG).
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal
from typing import Literal
from uuid import UUID

from app.domain.ledger import ZERO, Account, CashAccountRef, EntryDraft, LedgerRuleError, Line
from app.domain.money import CENT


def _positive_amount(amount: Decimal) -> Decimal:
    if amount <= 0:
        raise LedgerRuleError("amount must be greater than zero")
    if amount != amount.quantize(CENT):
        raise LedgerRuleError("amount has more than 2 decimals")
    return amount


def general_expense(
    *,
    entry_date: date,
    amount: Decimal,
    expense_account: Account,
    paid_from: CashAccountRef,
    description: str,
    source_id: UUID | None,
) -> EntryDraft:
    """Rule 20 — general expense paid in cash or by bank:
    Dr expense category account / Cr cash or bank."""
    amount = _positive_amount(amount)
    draft = EntryDraft(
        entry_date=entry_date,
        description=description,
        source_type="GENERAL_EXPENSE",
        source_id=source_id,
        lines=(
            Line(account=expense_account, debit=amount),
            Line(account=paid_from.account, credit=amount, cash_account_id=paid_from.cash_account_id),
        ),
    )
    draft.validate()
    return draft


def transfer(
    *,
    entry_date: date,
    amount: Decimal,
    source: CashAccountRef,
    destination: CashAccountRef,
    description: str,
    source_id: UUID | None,
) -> EntryDraft:
    """Rule 21 — cash <-> bank transfer: Dr destination / Cr source."""
    amount = _positive_amount(amount)
    if source.cash_account_id == destination.cash_account_id:
        raise LedgerRuleError("cannot transfer to the same account")
    draft = EntryDraft(
        entry_date=entry_date,
        description=description,
        source_type="TRANSFER",
        source_id=source_id,
        lines=(
            Line(account=destination.account, debit=amount, cash_account_id=destination.cash_account_id),
            Line(account=source.account, credit=amount, cash_account_id=source.cash_account_id),
        ),
    )
    draft.validate()
    return draft


def reversal_lines(original: Iterable[Line]) -> tuple[Line, ...]:
    """Rule 24 — the exact mirror: every debit becomes a credit and vice versa,
    with the same accounts, subledger ids and memos, in the same order."""
    mirrored = tuple(replace(line, debit=line.credit, credit=line.debit) for line in original)
    if sum((line.debit for line in mirrored), ZERO) != sum((line.credit for line in mirrored), ZERO):
        raise LedgerRuleError("original entry does not balance")
    return mirrored


# --- Partners (rules 1-5, 28, 29) --------------------------------------------------------

PartnerTransactionKind = Literal[
    "CONTRIBUTION",
    "CAPITAL_WITHDRAWAL",
    "DRAWING",
    "LOAN_TO_PARTNER",
    "LOAN_TO_PARTNER_REPAYMENT",
    "LOAN_FROM_PARTNER",
    "LOAN_FROM_PARTNER_REPAYMENT",
]

# kind -> (partner account system key, money comes IN to the showroom?, source_type)
PARTNER_TRANSACTION_RULES: dict[PartnerTransactionKind, tuple[str, bool, str]] = {
    "CONTRIBUTION": ("PARTNER_CAPITAL", True, "PARTNER_CONTRIBUTION"),  # rule 1
    "CAPITAL_WITHDRAWAL": ("PARTNER_CAPITAL", False, "PARTNER_CAPITAL_WITHDRAWAL"),  # rule 2
    "DRAWING": ("PARTNER_CURRENT", False, "PARTNER_DRAWING"),  # rule 3
    "LOAN_TO_PARTNER": ("PARTNER_LOANS_RECEIVABLE", False, "PARTNER_LOAN"),  # rule 4
    "LOAN_TO_PARTNER_REPAYMENT": ("PARTNER_LOANS_RECEIVABLE", True, "PARTNER_LOAN_REPAYMENT"),  # rule 5
    "LOAN_FROM_PARTNER": ("PARTNER_LOANS_PAYABLE", True, "PARTNER_LOAN_TO_BUSINESS"),  # rule 28
    "LOAN_FROM_PARTNER_REPAYMENT": ("PARTNER_LOANS_PAYABLE", False, "PARTNER_LOAN_TO_BUSINESS_REPAYMENT"),  # rule 29
}


def partner_transaction(
    *,
    kind: PartnerTransactionKind,
    entry_date: date,
    amount: Decimal,
    partner_id: UUID,
    cash: CashAccountRef,
    description: str,
    source_id: UUID | None,
) -> EntryDraft:
    """Rules 1-5, 28, 29: money between the showroom's cash/bank and a partner.

    Money in  (1 contribution, 5 loan repayment, 28 partner lends): Dr cash / Cr partner account.
    Money out (2 withdrawal, 3 drawing, 4 loan to partner, 29 repay partner): Dr partner account / Cr cash.
    """
    amount = _positive_amount(amount)
    account_key, money_in, source_type = PARTNER_TRANSACTION_RULES[kind]
    cash_line = Line(
        account=cash.account,
        debit=amount if money_in else ZERO,
        credit=ZERO if money_in else amount,
        cash_account_id=cash.cash_account_id,
    )
    partner_line = Line(
        account=Account.system(account_key),
        debit=ZERO if money_in else amount,
        credit=amount if money_in else ZERO,
        partner_id=partner_id,
    )
    draft = EntryDraft(
        entry_date=entry_date,
        description=description,
        source_type=source_type,
        source_id=source_id,
        lines=(cash_line, partner_line) if money_in else (partner_line, cash_line),
    )
    draft.validate()
    return draft


def general_expense_paid_by_partner(
    *,
    entry_date: date,
    amount: Decimal,
    expense_account: Account,
    partner_id: UUID,
    mode: Literal["CURRENT_ACCOUNT", "LOAN"],
    description: str,
    source_id: UUID | None,
) -> EntryDraft:
    """Rule 30 — a partner pays an expense personally: Dr expense /
    Cr partner current account (mode CURRENT_ACCOUNT) or loans from partners (mode LOAN).
    The vehicle-cost variant (Dr vehicle inventory) arrives with vehicles in Phase 4."""
    amount = _positive_amount(amount)
    credit_key = "PARTNER_CURRENT" if mode == "CURRENT_ACCOUNT" else "PARTNER_LOANS_PAYABLE"
    draft = EntryDraft(
        entry_date=entry_date,
        description=description,
        source_type="GENERAL_EXPENSE",
        source_id=source_id,
        lines=(
            Line(account=expense_account, debit=amount),
            Line(account=Account.system(credit_key), credit=amount, partner_id=partner_id),
        ),
    )
    draft.validate()
    return draft


def other_income(
    *, entry_date: date, amount: Decimal, received_in: CashAccountRef, description: str, source_id: UUID | None
) -> EntryDraft:
    """P-01 (approved 2026-10-02) — other income: Dr cash/bank / Cr 4900 other income."""
    amount = _positive_amount(amount)
    draft = EntryDraft(
        entry_date=entry_date,
        description=description,
        source_type="OTHER_INCOME",
        source_id=source_id,
        lines=(
            Line(account=received_in.account, debit=amount, cash_account_id=received_in.cash_account_id),
            Line(account=Account.system("OTHER_INCOME"), credit=amount),
        ),
    )
    draft.validate()
    return draft


# --- Purchases (rules 6, 7, 8) ---------------------------------------------------------------

CashLeg = tuple[CashAccountRef, Decimal]


def _cash_lines(legs: Sequence[CashLeg], *, money_in: bool) -> tuple[Line, ...]:
    lines = []
    for ref, amount in legs:
        positive = _positive_amount(amount)
        lines.append(
            Line(
                account=ref.account,
                debit=positive if money_in else ZERO,
                credit=ZERO if money_in else positive,
                cash_account_id=ref.cash_account_id,
            )
        )
    return tuple(lines)


def vehicle_purchase(
    *,
    entry_date: date,
    vehicle_id: UUID,
    seller_id: UUID,
    price: Decimal,
    payments: Sequence[CashLeg],
    description: str,
    source_id: UUID | None,
) -> EntryDraft:
    """Rules 6 and 7 — buy a car: Dr vehicle inventory (vehicle) / Cr each cash or
    bank leg, and Cr payable to the seller (seller + vehicle) for any unpaid part."""
    price = _positive_amount(price)
    paid_lines = _cash_lines(payments, money_in=False)
    deferred = price - sum((line.credit for line in paid_lines), ZERO)
    if deferred < 0:
        raise LedgerRuleError("payments exceed the purchase price")
    lines = [Line(account=Account.system("VEHICLE_INVENTORY"), debit=price, vehicle_id=vehicle_id), *paid_lines]
    if deferred > 0:
        lines.append(
            Line(
                account=Account.system("SELLER_PAYABLE"), credit=deferred, customer_id=seller_id, vehicle_id=vehicle_id
            )
        )
    draft = EntryDraft(
        entry_date=entry_date,
        description=description,
        source_type="VEHICLE_PURCHASE",
        source_id=source_id,
        lines=tuple(lines),
    )
    draft.validate()
    return draft


def seller_payment(
    *,
    entry_date: date,
    vehicle_id: UUID,
    seller_id: UUID,
    amount: Decimal,
    paid_from: CashAccountRef,
    description: str,
    source_id: UUID | None,
) -> EntryDraft:
    """Rule 8 — pay the seller later: Dr payable to seller (seller + vehicle) / Cr cash or bank."""
    amount = _positive_amount(amount)
    draft = EntryDraft(
        entry_date=entry_date,
        description=description,
        source_type="SELLER_PAYMENT",
        source_id=source_id,
        lines=(
            Line(account=Account.system("SELLER_PAYABLE"), debit=amount, customer_id=seller_id, vehicle_id=vehicle_id),
            Line(account=paid_from.account, credit=amount, cash_account_id=paid_from.cash_account_id),
        ),
    )
    draft.validate()
    return draft


# --- Vehicle expenses (rules 9, 30, 31; P-04) ---------------------------------------------------------


@dataclass(frozen=True)
class CashFunding:
    """Paid from a cash box or bank account (rule 9)."""

    paid_from: CashAccountRef


@dataclass(frozen=True)
class SupplierFunding:
    """On credit from a supplier or workshop (rule 31)."""

    supplier_id: UUID


@dataclass(frozen=True)
class PartnerFunding:
    """Paid personally by a partner (rule 30)."""

    partner_id: UUID
    mode: Literal["CURRENT_ACCOUNT", "LOAN"]


ExpenseFunding = CashFunding | SupplierFunding | PartnerFunding


def _funding_line(funding: ExpenseFunding, amount: Decimal) -> Line:
    if isinstance(funding, CashFunding):
        return Line(account=funding.paid_from.account, credit=amount, cash_account_id=funding.paid_from.cash_account_id)
    if isinstance(funding, SupplierFunding):
        return Line(account=Account.system("SUPPLIER_PAYABLE"), credit=amount, supplier_id=funding.supplier_id)
    key = "PARTNER_CURRENT" if funding.mode == "CURRENT_ACCOUNT" else "PARTNER_LOANS_PAYABLE"
    return Line(account=Account.system(key), credit=amount, partner_id=funding.partner_id)


def vehicle_expense(
    *,
    entry_date: date,
    vehicle_id: UUID,
    amount: Decimal,
    category_label: str,
    sold: bool,
    funding: ExpenseFunding,
    description: str,
    source_id: UUID | None,
) -> EntryDraft:
    """Rules 9, 30, 31 — an expense on an owned car is added to its cost:
    Dr vehicle inventory (vehicle, memo = category) / Cr cash, supplier payable or partner.
    P-04 (approved 2026-10-02): once the car is sold, Dr cost of vehicles sold instead."""
    amount = _positive_amount(amount)
    debit_key = "COST_OF_VEHICLES_SOLD" if sold else "VEHICLE_INVENTORY"
    draft = EntryDraft(
        entry_date=entry_date,
        description=description,
        source_type="VEHICLE_EXPENSE",
        source_id=source_id,
        lines=(
            Line(account=Account.system(debit_key), debit=amount, vehicle_id=vehicle_id, memo=category_label),
            _funding_line(funding, amount),
        ),
    )
    draft.validate()
    return draft


def general_expense_on_credit(
    *,
    entry_date: date,
    amount: Decimal,
    expense_account: Account,
    supplier_id: UUID,
    description: str,
    source_id: UUID | None,
) -> EntryDraft:
    """Rule 31 — a general expense or service on credit: Dr expense / Cr payable to suppliers (supplier)."""
    amount = _positive_amount(amount)
    draft = EntryDraft(
        entry_date=entry_date,
        description=description,
        source_type="GENERAL_EXPENSE",
        source_id=source_id,
        lines=(
            Line(account=expense_account, debit=amount),
            _funding_line(SupplierFunding(supplier_id), amount),
        ),
    )
    draft.validate()
    return draft


def supplier_payment(
    *,
    entry_date: date,
    supplier_id: UUID,
    amount: Decimal,
    paid_from: CashAccountRef,
    description: str,
    source_id: UUID | None,
) -> EntryDraft:
    """Rule 32 — pay a supplier: Dr payable to suppliers (supplier) / Cr cash or bank."""
    amount = _positive_amount(amount)
    draft = EntryDraft(
        entry_date=entry_date,
        description=description,
        source_type="SUPPLIER_PAYMENT",
        source_id=source_id,
        lines=(
            Line(account=Account.system("SUPPLIER_PAYABLE"), debit=amount, supplier_id=supplier_id),
            Line(account=paid_from.account, credit=amount, cash_account_id=paid_from.cash_account_id),
        ),
    )
    draft.validate()
    return draft


# --- Deposits (rules 11, 34, 35) -------------------------------------------------------------------------


def _deposit_line(customer_id: UUID, vehicle_id: UUID, *, debit: Decimal = ZERO, credit: Decimal = ZERO) -> Line:
    return Line(
        account=Account.system("CUSTOMER_DEPOSITS"),
        debit=debit,
        credit=credit,
        customer_id=customer_id,
        vehicle_id=vehicle_id,
    )


def deposit_received(
    *,
    entry_date: date,
    customer_id: UUID,
    vehicle_id: UUID,
    amount: Decimal,
    received_in: CashAccountRef,
    description: str,
    source_id: UUID | None,
) -> EntryDraft:
    """Rule 11 — customer deposit: Dr cash or bank / Cr customer deposits (customer + vehicle)."""
    amount = _positive_amount(amount)
    draft = EntryDraft(
        entry_date=entry_date,
        description=description,
        source_type="DEPOSIT",
        source_id=source_id,
        lines=(
            Line(account=received_in.account, debit=amount, cash_account_id=received_in.cash_account_id),
            _deposit_line(customer_id, vehicle_id, credit=amount),
        ),
    )
    draft.validate()
    return draft


def deposit_refunded(
    *,
    entry_date: date,
    customer_id: UUID,
    vehicle_id: UUID,
    amount: Decimal,
    paid_from: CashAccountRef,
    description: str,
    source_id: UUID | None,
) -> EntryDraft:
    """Rule 34 — deposit refunded: Dr customer deposits / Cr cash or bank."""
    amount = _positive_amount(amount)
    draft = EntryDraft(
        entry_date=entry_date,
        description=description,
        source_type="DEPOSIT_REFUND",
        source_id=source_id,
        lines=(
            _deposit_line(customer_id, vehicle_id, debit=amount),
            Line(account=paid_from.account, credit=amount, cash_account_id=paid_from.cash_account_id),
        ),
    )
    draft.validate()
    return draft


def deposit_forfeited(
    *, entry_date: date, customer_id: UUID, vehicle_id: UUID, amount: Decimal, description: str, source_id: UUID | None
) -> EntryDraft:
    """Rule 35 — deposit forfeited: Dr customer deposits / Cr other income."""
    amount = _positive_amount(amount)
    draft = EntryDraft(
        entry_date=entry_date,
        description=description,
        source_type="DEPOSIT_FORFEIT",
        source_id=source_id,
        lines=(
            _deposit_line(customer_id, vehicle_id, debit=amount),
            Line(account=Account.system("OTHER_INCOME"), credit=amount),
        ),
    )
    draft.validate()
    return draft


# --- Sales (rules 12, 26) --------------------------------------------------------------------------------


def sale(
    *,
    entry_date: date,
    vehicle_id: UUID,
    buyer_id: UUID,
    sale_price: Decimal,
    payments: Sequence[CashLeg],
    deposit_applied: Decimal,
    trade_in: tuple[UUID, Decimal] | None,
    description: str,
    source_id: UUID | None,
    financed: Decimal = ZERO,
    consignor_id: UUID | None = None,
    discount: Decimal = ZERO,
    markup: Decimal = ZERO,
) -> EntryDraft:
    """Rule 12 (cash/bank sale, deposit applied), rule 13 (the rest financed by
    installments, mode a: Dr installment receivable for the buyer) and rule 26 (trade-in):
    Dr each cash/bank leg + Dr customer deposits (buyer + vehicle) + Dr vehicle
    inventory (trade-in car, at the agreed value) / Cr vehicle sales (sold car).
    `sale_price` is the net price the buyer pays. A discount is its own line
    (P-12 as revised by the pilot review): Cr vehicle sales at the list price and
    Dr sales discounts (sold car), so revenue is still the net price.

    Rule 14 with the pilot's recognition (Q-03): an installment `markup` is added
    to the receivable and recognised at once, Cr installment financing income
    (buyer), instead of the deferred 2400 of the spec's illustration.

    Rule 16 entry A, a consigned-in car (`consignor_id` given): the full price is
    owed to the owner, so Cr payable to consignors (consignor + vehicle) instead
    of vehicle sales. P-14 has no candidate, so such a car is never financed."""
    sale_price = _positive_amount(sale_price)
    if consignor_id is not None and financed > 0:
        raise LedgerRuleError("a consigned car cannot be sold on installments (P-14)")
    lines = list(_cash_lines(payments, money_in=True))
    if deposit_applied > 0:
        lines.append(_deposit_line(buyer_id, vehicle_id, debit=_positive_amount(deposit_applied)))
    if trade_in is not None:
        trade_in_vehicle_id, value = trade_in
        if trade_in_vehicle_id == vehicle_id:
            raise LedgerRuleError("a car cannot be its own trade-in")
        lines.append(
            Line(
                account=Account.system("VEHICLE_INVENTORY"),
                debit=_positive_amount(value),
                vehicle_id=trade_in_vehicle_id,
            )
        )
    if markup < 0 or (markup > 0 and financed <= 0):
        raise LedgerRuleError("a markup needs an installment plan")
    if financed > 0:
        lines.append(
            Line(
                account=Account.system("INSTALLMENT_RECEIVABLE"),
                debit=_positive_amount(financed + markup),
                customer_id=buyer_id,
            )
        )
    if sum((line.debit for line in lines), ZERO) != sale_price + markup:
        raise LedgerRuleError("payments, deposit, trade-in and financed amount must add up to the sale price")
    if markup > 0:
        lines.append(Line(account=Account.system("INSTALLMENT_FINANCING_INCOME"), credit=markup, customer_id=buyer_id))
    if consignor_id is not None:
        lines.append(
            Line(
                account=Account.system("CONSIGNOR_PAYABLE"),
                credit=sale_price,
                consignor_id=consignor_id,
                vehicle_id=vehicle_id,
            )
        )
    else:
        if discount > 0:
            lines.append(
                Line(account=Account.system("SALES_DISCOUNTS"), debit=_positive_amount(discount), vehicle_id=vehicle_id)
            )
        lines.append(Line(account=Account.system("VEHICLE_SALES"), credit=sale_price + discount, vehicle_id=vehicle_id))
    draft = EntryDraft(
        entry_date=entry_date, description=description, source_type="SALE", source_id=source_id, lines=tuple(lines)
    )
    draft.validate()
    return draft


def cost_of_sale(
    *, entry_date: date, vehicle_id: UUID, cost: Decimal, description: str, source_id: UUID | None
) -> EntryDraft:
    """Rules 12/26 cost recognition (D-28, a second entry in the same transaction):
    Dr cost of vehicles sold / Cr vehicle inventory, both for the sold car, at its derived cost."""
    cost = _positive_amount(cost)
    draft = EntryDraft(
        entry_date=entry_date,
        description=description,
        source_type="SALE_COST",
        source_id=source_id,
        lines=(
            Line(account=Account.system("COST_OF_VEHICLES_SOLD"), debit=cost, vehicle_id=vehicle_id),
            Line(account=Account.system("VEHICLE_INVENTORY"), credit=cost, vehicle_id=vehicle_id),
        ),
    )
    draft.validate()
    return draft


def sale_cancellation_to_credit(
    *,
    entry_date: date,
    vehicle_id: UUID,
    buyer_id: UUID,
    sale_price: Decimal,
    amount_paid: Decimal,
    trade_in: tuple[UUID, Decimal] | None,
    description: str,
    source_id: UUID | None,
    receivable_outstanding: Decimal = ZERO,
    discount: Decimal = ZERO,
    markup: Decimal = ZERO,
) -> EntryDraft:
    """`discount` is the sales-discount line the sale itself posted (none for
    sales posted before discounts had their own line); `markup` the installment
    income it recognised, taken back out (Dr installment financing income).

    P-03 (approved as the default cancellation method, D-41): reverse the revenue
    and owe the customer what they paid: Dr vehicle sales / Cr customer credits
    (customer) for money paid and deposit applied, Cr vehicle inventory for a
    trade-in car handed back, and Cr installment receivable for what was still
    to be collected. The refund itself is posted separately (P-02)."""
    sale_price = _positive_amount(sale_price)
    lines = [Line(account=Account.system("VEHICLE_SALES"), debit=sale_price + discount, vehicle_id=vehicle_id)]
    if discount > 0:
        lines.append(
            Line(account=Account.system("SALES_DISCOUNTS"), credit=_positive_amount(discount), vehicle_id=vehicle_id)
        )
    if markup > 0:
        lines.append(Line(account=Account.system("INSTALLMENT_FINANCING_INCOME"), debit=markup, customer_id=buyer_id))
    if amount_paid > 0:
        lines.append(
            Line(account=Account.system("CUSTOMER_CREDITS"), credit=_positive_amount(amount_paid), customer_id=buyer_id)
        )
    if trade_in is not None:
        trade_in_vehicle_id, value = trade_in
        lines.append(
            Line(
                account=Account.system("VEHICLE_INVENTORY"),
                credit=_positive_amount(value),
                vehicle_id=trade_in_vehicle_id,
            )
        )
    if receivable_outstanding > 0:
        lines.append(
            Line(
                account=Account.system("INSTALLMENT_RECEIVABLE"),
                credit=_positive_amount(receivable_outstanding),
                customer_id=buyer_id,
            )
        )
    draft = EntryDraft(
        entry_date=entry_date,
        description=description,
        source_type="SALE_CANCELLATION",
        source_id=source_id,
        lines=tuple(lines),
    )
    draft.validate()
    return draft


def trade_in_expenses_to_customer(
    *,
    entry_date: date,
    trade_in_vehicle_id: UUID,
    customer_id: UUID,
    amount: Decimal,
    from_credit: Decimal,
    description: str,
    source_id: UUID | None,
) -> EntryDraft:
    """Pilot review (D-76 revised): a cancelled sale hands the trade-in car back with
    what we spent on it charged to the customer. Dr customer credits (customer) for
    the part taken off their refund, Dr other receivables (customer) for any rest
    they owe us / Cr vehicle inventory (trade-in car), so the car leaves stock in full."""
    amount = _positive_amount(amount)
    if from_credit < 0 or from_credit > amount:
        raise LedgerRuleError("the part taken from the customer's credit must be between zero and the amount")
    lines = []
    if from_credit > 0:
        lines.append(Line(account=Account.system("CUSTOMER_CREDITS"), debit=from_credit, customer_id=customer_id))
    if amount > from_credit:
        lines.append(
            Line(account=Account.system("OTHER_RECEIVABLE"), debit=amount - from_credit, customer_id=customer_id)
        )
    lines.append(Line(account=Account.system("VEHICLE_INVENTORY"), credit=amount, vehicle_id=trade_in_vehicle_id))
    draft = EntryDraft(
        entry_date=entry_date,
        description=description,
        source_type="SALE_CANCELLATION",
        source_id=source_id,
        lines=tuple(lines),
    )
    draft.validate()
    return draft


def customer_credit_refund(
    *,
    entry_date: date,
    customer_id: UUID,
    amount: Decimal,
    paid_from: CashAccountRef,
    description: str,
    source_id: UUID | None,
) -> EntryDraft:
    """P-02 refund leg (approved, D-41): Dr customer credits (customer) / Cr cash or bank."""
    amount = _positive_amount(amount)
    draft = EntryDraft(
        entry_date=entry_date,
        description=description,
        source_type="CUSTOMER_REFUND",
        source_id=source_id,
        lines=(
            Line(account=Account.system("CUSTOMER_CREDITS"), debit=amount, customer_id=customer_id),
            Line(account=paid_from.account, credit=amount, cash_account_id=paid_from.cash_account_id),
        ),
    )
    draft.validate()
    return draft


# --- Installments (rules 15, 27; P-02 credit legs; P-07) ------------------------------------------


def installment_receipt(
    *,
    entry_date: date,
    customer_id: UUID,
    allocated: Decimal,
    received_in: CashAccountRef | None,
    excess_to_credit: Decimal,
    description: str,
    source_id: UUID | None,
) -> EntryDraft:
    """Rule 15 (mode a) — installment collected: Dr cash or bank / Cr installment
    receivable (customer). P-02 (approved, D-41): an overpayment kept as credit is
    Cr customer credits; paying from existing credit is Dr customer credits instead of cash."""
    allocated = _positive_amount(allocated)
    if received_in is None:
        if excess_to_credit > 0:
            raise LedgerRuleError("credit cannot be turned into more credit")
        first = Line(account=Account.system("CUSTOMER_CREDITS"), debit=allocated, customer_id=customer_id)
    else:
        total = allocated + (excess_to_credit if excess_to_credit > 0 else ZERO)
        first = Line(account=received_in.account, debit=total, cash_account_id=received_in.cash_account_id)
    lines = [first, Line(account=Account.system("INSTALLMENT_RECEIVABLE"), credit=allocated, customer_id=customer_id)]
    if excess_to_credit > 0:
        lines.append(
            Line(
                account=Account.system("CUSTOMER_CREDITS"),
                credit=_positive_amount(excess_to_credit),
                customer_id=customer_id,
            )
        )
    draft = EntryDraft(
        entry_date=entry_date,
        description=description,
        source_type="INSTALLMENT_RECEIPT",
        source_id=source_id,
        lines=tuple(lines),
    )
    draft.validate()
    return draft


def cheque_bounced(
    *,
    entry_date: date,
    customer_id: UUID,
    amount: Decimal,
    bank: CashAccountRef,
    description: str,
    source_id: UUID | None,
) -> EntryDraft:
    """Rule 27 — a cheque already recorded as collected bounces: Dr installment
    receivable (customer) / Cr bank. The installment balance reopens."""
    amount = _positive_amount(amount)
    draft = EntryDraft(
        entry_date=entry_date,
        description=description,
        source_type="CHEQUE_BOUNCE",
        source_id=source_id,
        lines=(
            Line(account=Account.system("INSTALLMENT_RECEIVABLE"), debit=amount, customer_id=customer_id),
            Line(account=bank.account, credit=amount, cash_account_id=bank.cash_account_id),
        ),
    )
    draft.validate()
    return draft


def bounce_charges(
    *,
    entry_date: date,
    amount: Decimal,
    bank: CashAccountRef,
    charge_customer_id: UUID | None,
    description: str,
    source_id: UUID | None,
) -> EntryDraft:
    """P-07 (approved 2026-10-02) — bank charges on a bounced cheque: Dr bank
    charges (6270) / Cr bank, or, when recharged to the customer, Dr other
    receivables (customer) / Cr bank."""
    amount = _positive_amount(amount)
    debit = (
        Line(account=Account.system("OTHER_RECEIVABLE"), debit=amount, customer_id=charge_customer_id)
        if charge_customer_id is not None
        else Line(account=Account.system("EXP_BANK_CHARGES"), debit=amount)
    )
    draft = EntryDraft(
        entry_date=entry_date,
        description=description,
        source_type="BANK_CHARGES",
        source_id=source_id,
        lines=(debit, Line(account=bank.account, credit=amount, cash_account_id=bank.cash_account_id)),
    )
    draft.validate()
    return draft


# --- Consignment in (rules 10, 16, 17; P-05, P-06) -----------------------------------------------


def consigned_vehicle_expense(
    *,
    entry_date: date,
    vehicle_id: UUID,
    consignor_id: UUID,
    amount: Decimal,
    owner_part: Decimal,
    category_label: str,
    funding: ExpenseFunding,
    description: str,
    source_id: UUID | None,
) -> EntryDraft:
    """Rule 10: an expense on a consigned-in car is recoverable from the owner:
    Dr recoverable from consignors (consignor + vehicle) / Cr the funding. With
    partner or supplier funding this is C-11's default (never vehicle inventory).
    P-05 (approved 2026-10-02): the part the showroom bears is Dr 6280
    consigned-car expenses (vehicle); a shared expense is split between the two."""
    amount = _positive_amount(amount)
    if owner_part < 0 or owner_part > amount:
        raise LedgerRuleError("the owner's part must be between zero and the expense")
    showroom_part = amount - owner_part
    lines = []
    if owner_part > 0:
        lines.append(
            Line(
                account=Account.system("CONSIGNOR_RECOVERABLE"),
                debit=owner_part,
                consignor_id=consignor_id,
                vehicle_id=vehicle_id,
                memo=category_label,
            )
        )
    if showroom_part > 0:
        lines.append(
            Line(
                account=Account.system("EXP_CONSIGNMENT"),
                debit=showroom_part,
                vehicle_id=vehicle_id,
                memo=category_label,
            )
        )
    lines.append(_funding_line(funding, amount))
    draft = EntryDraft(
        entry_date=entry_date,
        description=description,
        source_type="VEHICLE_EXPENSE",
        source_id=source_id,
        lines=tuple(lines),
    )
    draft.validate()
    return draft


def consignment_commission(
    *,
    entry_date: date,
    vehicle_id: UUID,
    consignor_id: UUID,
    commission: Decimal,
    recovered: Decimal,
    description: str,
    source_id: UUID | None,
) -> EntryDraft:
    """Rule 16 entry B: on the sale of a consigned-in car, keep the commission and
    recover the owner's expenses from what is owed to them: Dr payable to consignors
    (commission + recovered) / Cr consignment commission (vehicle) + Cr recoverable
    from consignors (consignor + vehicle)."""
    commission = _positive_amount(commission)
    if recovered < 0:
        raise LedgerRuleError("recovered expenses cannot be negative")
    lines = [
        Line(
            account=Account.system("CONSIGNOR_PAYABLE"),
            debit=commission + recovered,
            consignor_id=consignor_id,
            vehicle_id=vehicle_id,
        ),
        Line(account=Account.system("CONSIGNMENT_COMMISSION"), credit=commission, vehicle_id=vehicle_id),
    ]
    if recovered > 0:
        lines.append(
            Line(
                account=Account.system("CONSIGNOR_RECOVERABLE"),
                credit=_positive_amount(recovered),
                consignor_id=consignor_id,
                vehicle_id=vehicle_id,
            )
        )
    draft = EntryDraft(
        entry_date=entry_date,
        description=description,
        source_type="CONSIGNMENT_COMMISSION",
        source_id=source_id,
        lines=tuple(lines),
    )
    draft.validate()
    return draft


def consignor_payout(
    *,
    entry_date: date,
    vehicle_id: UUID,
    consignor_id: UUID,
    amount: Decimal,
    paid_from: CashAccountRef,
    description: str,
    source_id: UUID | None,
) -> EntryDraft:
    """Rule 17: pay the consignor: Dr payable to consignors (consignor + vehicle) / Cr cash or bank."""
    amount = _positive_amount(amount)
    draft = EntryDraft(
        entry_date=entry_date,
        description=description,
        source_type="CONSIGNOR_PAYOUT",
        source_id=source_id,
        lines=(
            Line(
                account=Account.system("CONSIGNOR_PAYABLE"),
                debit=amount,
                consignor_id=consignor_id,
                vehicle_id=vehicle_id,
            ),
            Line(account=paid_from.account, credit=amount, cash_account_id=paid_from.cash_account_id),
        ),
    )
    draft.validate()
    return draft


def consignor_recovery(
    *,
    entry_date: date,
    vehicle_id: UUID,
    consignor_id: UUID,
    amount: Decimal,
    received_in: CashAccountRef,
    description: str,
    source_id: UUID | None,
) -> EntryDraft:
    """P-06 (approved 2026-10-02): the owner repays recoverable expenses, for
    example when the car goes back unsold: Dr cash or bank / Cr recoverable from
    consignors (consignor + vehicle)."""
    amount = _positive_amount(amount)
    draft = EntryDraft(
        entry_date=entry_date,
        description=description,
        source_type="CONSIGNOR_RECOVERY",
        source_id=source_id,
        lines=(
            Line(account=received_in.account, debit=amount, cash_account_id=received_in.cash_account_id),
            Line(
                account=Account.system("CONSIGNOR_RECOVERABLE"),
                credit=amount,
                consignor_id=consignor_id,
                vehicle_id=vehicle_id,
            ),
        ),
    )
    draft.validate()
    return draft


# --- Consignment out (rules 18, 19) ----------------------------------------------------------------


def _receivable_line(
    external_showroom_id: UUID, vehicle_id: UUID | None, *, debit: Decimal = ZERO, credit: Decimal = ZERO
) -> Line:
    return Line(
        account=Account.system("EXTERNAL_SHOWROOM_RECEIVABLE"),
        debit=debit,
        credit=credit,
        external_showroom_id=external_showroom_id,
        vehicle_id=vehicle_id,
    )


def external_sale(
    *,
    entry_date: date,
    vehicle_id: UUID,
    external_showroom_id: UUID,
    sale_price: Decimal,
    description: str,
    source_id: UUID | None,
) -> EntryDraft:
    """Rule 18, first entry: our car sold by an external showroom: Dr receivable
    from external showrooms (showroom + vehicle) / Cr vehicle sales (vehicle)."""
    sale_price = _positive_amount(sale_price)
    draft = EntryDraft(
        entry_date=entry_date,
        description=description,
        source_type="SALE",
        source_id=source_id,
        lines=(
            _receivable_line(external_showroom_id, vehicle_id, debit=sale_price),
            Line(account=Account.system("VEHICLE_SALES"), credit=sale_price, vehicle_id=vehicle_id),
        ),
    )
    draft.validate()
    return draft


def external_commission(
    *,
    entry_date: date,
    vehicle_id: UUID,
    external_showroom_id: UUID,
    commission: Decimal,
    description: str,
    source_id: UUID | None,
) -> EntryDraft:
    """Rule 18, second entry: the showroom keeps its commission: Dr commission to
    external showrooms (showroom + vehicle) / Cr receivable from external showrooms.
    The third entry is the cost of sale (`cost_of_sale`)."""
    commission = _positive_amount(commission)
    draft = EntryDraft(
        entry_date=entry_date,
        description=description,
        source_type="EXTERNAL_COMMISSION",
        source_id=source_id,
        lines=(
            Line(
                account=Account.system("EXTERNAL_COMMISSION_EXPENSE"),
                debit=commission,
                external_showroom_id=external_showroom_id,
                vehicle_id=vehicle_id,
            ),
            _receivable_line(external_showroom_id, vehicle_id, credit=commission),
        ),
    )
    draft.validate()
    return draft


def external_collection(
    *,
    entry_date: date,
    external_showroom_id: UUID,
    amount: Decimal,
    received_in: CashAccountRef,
    description: str,
    source_id: UUID | None,
) -> EntryDraft:
    """Rule 19: collect from the external showroom: Dr cash or bank / Cr receivable
    from external showrooms (showroom)."""
    amount = _positive_amount(amount)
    draft = EntryDraft(
        entry_date=entry_date,
        description=description,
        source_type="EXTERNAL_COLLECTION",
        source_id=source_id,
        lines=(
            Line(account=received_in.account, debit=amount, cash_account_id=received_in.cash_account_id),
            _receivable_line(external_showroom_id, None, credit=amount),
        ),
    )
    draft.validate()
    return draft


# --- Period close and distribution (rules 22, 23; P-09, P-10) ---------------------------------


def _signed(account: Account, amount: Decimal, **ids: UUID | None) -> Line:
    """A line that adds `amount` to a credit balance (negative amounts debit)."""
    return Line(
        account=account,
        debit=-amount if amount < 0 else ZERO,
        credit=amount if amount > 0 else ZERO,
        **ids,  # type: ignore[arg-type]
    )


def period_close(*, entry_date: date, balances: Sequence[Line], description: str, source_id: UUID | None) -> EntryDraft:
    """Rule 23 — close the period's income and expense balances (each given as a
    line carrying its balance, with its subledger ids) into retained earnings:
    the mirror of every balance, and Cr 3300 the net profit (Dr for a loss).
    The entry is a closing entry, left out of the P&L (D-29)."""
    lines = [replace(line, debit=line.credit, credit=line.debit) for line in balances if line.debit != line.credit]
    if not lines:
        raise LedgerRuleError("nothing to close")
    net = sum((line.debit - line.credit for line in lines), ZERO)
    if net != 0:
        lines.append(_signed(Account.system("RETAINED_EARNINGS"), net))
    draft = EntryDraft(
        entry_date=entry_date,
        description=description,
        source_type="PERIOD_CLOSE",
        source_id=source_id,
        lines=tuple(lines),
        is_closing=True,
    )
    draft.validate()
    return draft


def _partner_lines(account_key: str, shares: Sequence[tuple[UUID, Decimal]]) -> list[Line]:
    return [
        _signed(Account.system(account_key), amount, partner_id=partner_id)
        for partner_id, amount in shares
        if amount != 0
    ]


def profit_distribution(
    *, entry_date: date, shares: Sequence[tuple[UUID, Decimal]], description: str, source_id: UUID | None
) -> EntryDraft:
    """Rule 22 — distribute undistributed profit: Dr 3300 / Cr 3200 per partner.
    P-09 (approved as option D-40): a loss is the opposite, Dr 3200 per partner / Cr 3300."""
    partner_lines = _partner_lines("PARTNER_CURRENT", shares)
    total = sum((line.credit - line.debit for line in partner_lines), ZERO)
    if not partner_lines or total == 0:
        raise LedgerRuleError("nothing to distribute")
    retained = _signed(Account.system("RETAINED_EARNINGS"), -total)
    lines = [retained, *partner_lines] if total > 0 else [*partner_lines, retained]
    draft = EntryDraft(
        entry_date=entry_date,
        description=description,
        source_type="PROFIT_DISTRIBUTION",
        source_id=source_id,
        lines=tuple(lines),
        is_closing=True,
    )
    draft.validate()
    return draft


def profit_allocation(
    *, entry_date: date, shares: Sequence[tuple[UUID, Decimal]], description: str, source_id: UUID | None
) -> EntryDraft:
    """P-10 (per-car policy, D-40) — a sale's gross profit allocated at once:
    Dr 3310 Profit allocated in advance / Cr 3200 per partner (the reverse for a loss)."""
    partner_lines = _partner_lines("PARTNER_CURRENT", shares)
    total = sum((line.credit - line.debit for line in partner_lines), ZERO)
    if not partner_lines or total == 0:
        raise LedgerRuleError("nothing to allocate")
    advance = _signed(Account.system("PROFIT_ALLOCATED_IN_ADVANCE"), -total)
    lines = [advance, *partner_lines] if total > 0 else [*partner_lines, advance]
    draft = EntryDraft(
        entry_date=entry_date,
        description=description,
        source_type="PROFIT_ALLOCATION",
        source_id=source_id,
        lines=tuple(lines),
    )
    draft.validate()
    return draft


def advance_netting(*, entry_date: date, amount: Decimal, description: str, source_id: UUID | None) -> EntryDraft:
    """P-10 at period close: the profit already allocated per car is netted
    against the closed profit: Dr 3300 / Cr 3310 (the reverse when it was a loss)."""
    if amount == 0:
        raise LedgerRuleError("nothing to net")
    lines = (
        _signed(Account.system("RETAINED_EARNINGS"), -amount),
        _signed(Account.system("PROFIT_ALLOCATED_IN_ADVANCE"), amount),
    )
    draft = EntryDraft(
        entry_date=entry_date,
        description=description,
        source_type="PROFIT_NETTING",
        source_id=source_id,
        lines=lines if amount > 0 else (lines[1], lines[0]),
        is_closing=True,
    )
    draft.validate()
    return draft


# --- Opening balances (rule 25; P-08) ---------------------------------------------------------------


def opening_balances(
    *, entry_date: date, lines: Sequence[Line], description: str, source_id: UUID | None
) -> EntryDraft:
    """Rule 25 — the single opening entry at go-live: every imported balance, and
    opening balance equity (3900) for the difference (Q-16 decides where it goes)."""
    balances = [line for line in lines if line.debit != line.credit]
    if not balances:
        raise LedgerRuleError("no opening balances")
    net = sum((line.debit - line.credit for line in balances), ZERO)
    if net != 0:
        balances.append(_signed(Account.system("OPENING_BALANCE_EQUITY"), net))
    draft = EntryDraft(
        entry_date=entry_date,
        description=description,
        source_type="OPENING_BALANCE",
        source_id=source_id,
        lines=tuple(balances),
        is_opening=True,
    )
    draft.validate()
    return draft


def opening_equity_clearing(
    *,
    entry_date: date,
    allocations: Sequence[tuple[UUID, Literal["CAPITAL", "CURRENT"], Decimal]],
    description: str,
    source_id: UUID | None,
) -> EntryDraft:
    """P-08 (approved 2026-10-02: by agreement) — clear opening balance equity into
    partner capital or current accounts: Dr 3900 / Cr 3100 or 3200 per partner."""
    partner_lines = [
        Line(
            account=Account.system("PARTNER_CAPITAL" if account == "CAPITAL" else "PARTNER_CURRENT"),
            credit=_positive_amount(amount),
            partner_id=partner_id,
        )
        for partner_id, account, amount in allocations
    ]
    total = sum((line.credit for line in partner_lines), ZERO)
    draft = EntryDraft(
        entry_date=entry_date,
        description=description,
        source_type="OPENING_EQUITY_CLEARING",
        source_id=source_id,
        lines=(Line(account=Account.system("OPENING_BALANCE_EQUITY"), debit=total), *partner_lines),
    )
    draft.validate()
    return draft
