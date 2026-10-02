"""Posting rules (docs/ACCOUNTING.md §3). Pure functions: command in, balanced
draft out. Unit-tested in tests/unit/test_posting_rules.py.

Implemented: 1-5, 28, 29 (partners), 6-9 (purchase, seller payment, vehicle
expense), 11, 34, 35 (deposits), 12, 26 (sale, trade-in, cost recognition),
20, 21 (general expense, transfer), 24 (reversal; the database performs it,
this mirror is used for previews and cash checks), 30-32 (partner-paid and
supplier-credit expenses, supplier payment), and the approved candidates
P-01, P-02, P-03, P-04. Further rules arrive with their phases (BACKLOG).
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
) -> EntryDraft:
    """Rule 12 (cash/bank sale, deposit applied) and rule 26 (trade-in):
    Dr each cash/bank leg + Dr customer deposits (buyer + vehicle) + Dr vehicle
    inventory (trade-in car, at the agreed value) / Cr vehicle sales (sold car).
    The sale price is the net price after any discount (P-12)."""
    sale_price = _positive_amount(sale_price)
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
    if sum((line.debit for line in lines), ZERO) != sale_price:
        raise LedgerRuleError("payments, deposit and trade-in must add up to the sale price")
    lines.append(Line(account=Account.system("VEHICLE_SALES"), credit=sale_price, vehicle_id=vehicle_id))
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
) -> EntryDraft:
    """P-03 (approved as the default cancellation method, D-41): reverse the revenue
    and owe the customer what they paid: Dr vehicle sales / Cr customer credits
    (customer) for money paid and deposit applied, Cr vehicle inventory for a
    trade-in car handed back. The refund itself is posted separately (P-02)."""
    sale_price = _positive_amount(sale_price)
    lines = [Line(account=Account.system("VEHICLE_SALES"), debit=sale_price, vehicle_id=vehicle_id)]
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
