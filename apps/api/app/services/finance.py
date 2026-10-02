"""Cash and bank: accounts, expense categories, general expenses (rule 20),
transfers (rule 21), the cash-negative policy and the cash book.

Every money-moving function runs inside the caller's transaction and posts
through app.services.posting.engine — never by writing ledger tables.
"""

import re
from dataclasses import dataclass, replace
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import Connection, text

from app.core.errors import AppError, not_found
from app.domain.finance import (
    CashAccountIn,
    CashAccountOut,
    CashAccountUpdate,
    CashBookMovement,
    CashBookOut,
    EntryRef,
    ExpenseCategoryIn,
    ExpenseCategoryOut,
    ExpenseCategoryUpdate,
    GeneralExpenseIn,
    GeneralExpenseOut,
    Page,
    PaymentMethodOut,
    PostingResult,
    PostingWarning,
    Preview,
    PreviewEffect,
    PreviewLine,
    TransferIn,
    TransferOut,
)
from app.domain.ledger import ZERO, Account, CashAccountRef, EntryDraft
from app.domain.money import format_money, ltr
from app.services.posting import engine, rules

# --- Tenant context -------------------------------------------------------------------


@dataclass(frozen=True)
class TenantInfo:
    currency: str
    timezone: str
    cash_negative_policy: str

    @property
    def today(self) -> date:
        return datetime.now(ZoneInfo(self.timezone)).date()


_TENANT_INFO = text(
    """
    select t.currency_code, t.timezone, s.cash_negative_policy
      from public.tenants t join public.tenant_settings s on s.tenant_id = t.id
     where t.id = private.current_tenant_id()
    """
)


def tenant_info(conn: Connection) -> TenantInfo:
    row = conn.execute(_TENANT_INFO).one()
    return TenantInfo(currency=row.currency_code, timezone=row.timezone, cash_negative_policy=row.cash_negative_policy)


def check_entry_date(info: TenantInfo, entry_date: date) -> None:
    """DECISION D-52: no postings dated after today (tenant timezone)."""
    if entry_date > info.today:
        raise AppError(
            "DATE_IN_FUTURE",
            "The date cannot be in the future",
            status_code=422,
            details={"today": info.today.isoformat()},
        )


_PERIOD_STATUS = text(
    "select status from public.accounting_periods where month = :month and tenant_id = private.current_tenant_id()"
)


def ensure_period_open(conn: Connection, entry_date: date) -> None:
    """Early, friendly check for previews; the database enforces it again on posting."""
    month = entry_date.replace(day=1)
    if conn.execute(_PERIOD_STATUS, {"month": month}).scalar_one_or_none() == "LOCKED":
        raise AppError(
            "PERIOD_LOCKED",
            "The accounting month is locked",
            status_code=422,
            details={"period": f"{month:%Y-%m}"},
        )


# --- Cash and bank accounts ------------------------------------------------------------------

_CASH_ACCOUNTS = """
    select ca.id, ca.kind, ca.name_ar, ca.name_en, la.code as ledger_account_code, ca.bank_name,
           ca.account_number, ca.iban, ca.is_default, ca.archived_at is not null as archived,
           ca.ledger_account_id,
           coalesce((select sum(l.debit - l.credit) from public.journal_lines l
                      where l.tenant_id = ca.tenant_id and l.cash_account_id = ca.id), 0) as balance
      from public.cash_accounts ca
      join public.ledger_accounts la on la.id = ca.ledger_account_id
"""


def list_cash_accounts(conn: Connection, include_archived: bool = False) -> list[CashAccountOut]:
    where = "" if include_archived else " where ca.archived_at is null"
    rows = conn.execute(text(_CASH_ACCOUNTS + where + " order by ca.is_default desc, ca.kind, la.code")).mappings()
    return [CashAccountOut.model_validate(dict(row)) for row in rows]


def get_cash_account(conn: Connection, cash_account_id: UUID) -> CashAccountOut:
    row = conn.execute(text(_CASH_ACCOUNTS + " where ca.id = :id"), {"id": cash_account_id}).mappings().first()
    if row is None:
        raise not_found("cash account")
    return CashAccountOut.model_validate(dict(row))


def _next_child_code(conn: Connection, system_key: str) -> tuple[UUID, str]:
    """Next free 4-digit code under a parent account, e.g. 1101, 1102... under 1100.

    The parent row is locked so two concurrent creations cannot take the same code.
    """
    parent = conn.execute(
        text("select id, code from public.ledger_accounts where system_key = :key for update"),
        {"key": system_key},
    ).one()
    used = conn.execute(
        text("select coalesce(max(code::int), :base) from public.ledger_accounts where parent_id = :parent"),
        {"base": int(parent.code), "parent": parent.id},
    ).scalar_one()
    code = int(used) + 1
    if code >= int(parent.code) + 100:
        raise AppError("ACCOUNT_LIMIT_REACHED", "No more sub-account codes available", status_code=422)
    return parent.id, str(code)


_INSERT_LEDGER_ACCOUNT = text(
    """
    insert into public.ledger_accounts
      (tenant_id, code, parent_id, name_ar, name_en, type, normal_side, is_postable, is_system, subledger)
    values
      (private.current_tenant_id(), :code, :parent_id, :name_ar, :name_en, :type, :normal_side, true, false, :subledger)
    returning id
    """
)


def create_cash_account(conn: Connection, payload: CashAccountIn) -> CashAccountOut:
    parent_id, code = _next_child_code(conn, "CASH_BOXES" if payload.kind == "CASH_BOX" else "BANK_ACCOUNTS")
    ledger_account_id = conn.execute(
        _INSERT_LEDGER_ACCOUNT,
        {
            "code": code,
            "parent_id": parent_id,
            "name_ar": payload.name_ar,
            "name_en": payload.name_en or payload.name_ar,
            "type": "ASSET",
            "normal_side": "DEBIT",
            "subledger": "CASH_ACCOUNT",
        },
    ).scalar_one()

    has_default = conn.execute(
        text("select exists (select 1 from public.cash_accounts where is_default and archived_at is null)")
    ).scalar_one()
    make_default = payload.is_default or not has_default
    if make_default:
        conn.execute(text("update public.cash_accounts set is_default = false where is_default"))

    new_id = conn.execute(
        text(
            """
            insert into public.cash_accounts
              (tenant_id, kind, name_ar, name_en, ledger_account_id, bank_name, account_number, iban, is_default)
            values
              (private.current_tenant_id(), :kind, :name_ar, :name_en, :ledger_account_id, :bank_name,
               :account_number, :iban, :is_default)
            returning id
            """
        ),
        {
            **payload.model_dump(exclude={"is_default"}),
            "ledger_account_id": ledger_account_id,
            "is_default": make_default,
        },
    ).scalar_one()
    return get_cash_account(conn, new_id)


def update_cash_account(conn: Connection, cash_account_id: UUID, changes: CashAccountUpdate) -> CashAccountOut:
    current = conn.execute(
        text("select id, ledger_account_id, is_default from public.cash_accounts where id = :id for update"),
        {"id": cash_account_id},
    ).first()
    if current is None:
        raise not_found("cash account")
    values = changes.model_dump(exclude_unset=True, exclude={"archived", "is_default"})

    if changes.archived is True:
        if get_cash_account(conn, cash_account_id).balance != 0:
            raise AppError(
                "CASH_ACCOUNT_NOT_EMPTY",
                "Only an account with a zero balance can be archived",
                status_code=409,
            )
        conn.execute(
            text("update public.cash_accounts set archived_at = now(), is_default = false where id = :id"),
            {"id": cash_account_id},
        )
    elif changes.archived is False:
        conn.execute(text("update public.cash_accounts set archived_at = null where id = :id"), {"id": cash_account_id})

    if changes.is_default:
        conn.execute(
            text("update public.cash_accounts set is_default = false where is_default and id <> :id"),
            {"id": cash_account_id},
        )
        conn.execute(text("update public.cash_accounts set is_default = true where id = :id"), {"id": cash_account_id})

    if values:
        assignments = ", ".join(f"{column} = :{column}" for column in values)  # keys from a StrictModel
        conn.execute(
            text(f"update public.cash_accounts set {assignments} where id = :id"),  # noqa: S608
            {**values, "id": cash_account_id},
        )
        if "name_ar" in values or "name_en" in values:
            conn.execute(
                text(
                    """
                    update public.ledger_accounts la
                       set name_ar = ca.name_ar, name_en = coalesce(ca.name_en, ca.name_ar)
                      from public.cash_accounts ca
                     where ca.id = :id and la.id = ca.ledger_account_id
                    """
                ),
                {"id": cash_account_id},
            )
    return get_cash_account(conn, cash_account_id)


@dataclass(frozen=True)
class _ActiveCashAccount:
    ref: CashAccountRef
    name_ar: str
    name_en: str


def _active_cash_account(conn: Connection, cash_account_id: UUID) -> _ActiveCashAccount:
    row = conn.execute(
        text(
            "select id, ledger_account_id, name_ar, name_en from public.cash_accounts "
            "where id = :id and archived_at is null"
        ),
        {"id": cash_account_id},
    ).first()
    if row is None:
        raise AppError(
            "CASH_ACCOUNT_INVALID",
            "Unknown or archived cash/bank account",
            status_code=422,
            details={"cash_account_id": str(cash_account_id)},
        )
    return _ActiveCashAccount(
        ref=CashAccountRef(cash_account_id=row.id, ledger_account_id=row.ledger_account_id),
        name_ar=row.name_ar,
        name_en=row.name_en or row.name_ar,
    )


# --- Cash-negative policy (SPEC §3.4: warn vs block) -----------------------------------------


def check_cash(conn: Connection, info: TenantInfo, effects: dict[UUID, Decimal], *, lock: bool) -> list[PostingWarning]:
    """Check accounts that would go below zero. With lock=True (real posting)
    the cash account rows are locked in id order, so two concurrent payments
    cannot both pass the check on the same balance."""
    warnings: list[PostingWarning] = []
    for cash_account_id in sorted(effects, key=str):
        delta = effects[cash_account_id]
        if delta >= 0:
            continue
        if lock:
            conn.execute(text("select 1 from public.cash_accounts where id = :id for update"), {"id": cash_account_id})
        account = get_cash_account(conn, cash_account_id)
        after = account.balance + delta
        if after >= 0:
            continue
        details: dict[str, object] = {
            "cash_account_id": str(cash_account_id),
            "name_ar": account.name_ar,
            "name_en": account.name_en or account.name_ar,
            "balance": f"{account.balance:.2f}",
            "balance_after": f"{after:.2f}",
        }
        if info.cash_negative_policy == "BLOCK":
            raise AppError("CASH_INSUFFICIENT", "Not enough money in the account", status_code=422, details=details)
        warnings.append(PostingWarning(code="CASH_NEGATIVE", details=details))
    return warnings


# --- Expense categories and payment methods -----------------------------------------------------

_CATEGORIES = """
    select ec.id, ec.kind, ec.code, ec.name_ar, ec.name_en, la.code as ledger_account_code, ec.is_seeded,
           ec.archived_at is not null as archived
      from public.expense_categories ec
      left join public.ledger_accounts la on la.id = ec.ledger_account_id
"""


def list_categories(conn: Connection, kind: str | None, include_archived: bool) -> list[ExpenseCategoryOut]:
    clauses = []
    if kind:
        clauses.append("ec.kind = :kind")
    if not include_archived:
        clauses.append("ec.archived_at is null")
    where = (" where " + " and ".join(clauses)) if clauses else ""
    rows = conn.execute(text(_CATEGORIES + where + " order by ec.kind, ec.sort_order, ec.name_en"), {"kind": kind})
    return [ExpenseCategoryOut.model_validate(dict(row)) for row in rows.mappings()]


def _get_category(conn: Connection, category_id: UUID) -> ExpenseCategoryOut:
    row = conn.execute(text(_CATEGORIES + " where ec.id = :id"), {"id": category_id}).mappings().first()
    if row is None:
        raise not_found("expense category")
    return ExpenseCategoryOut.model_validate(dict(row))


def _slug(name: str) -> str:
    slug = re.sub(r"[^a-z]+", "_", name.lower()).strip("_")
    return slug or "category"


def create_category(conn: Connection, payload: ExpenseCategoryIn) -> ExpenseCategoryOut:
    base = _slug(payload.name_en)
    taken = set(
        conn.execute(
            text("select code from public.expense_categories where kind = :kind and code like :prefix"),
            {"kind": payload.kind, "prefix": f"{base}%"},
        ).scalars()
    )
    code, suffix = base, 2
    while code in taken:
        code, suffix = f"{base}_{_letters(suffix)}", suffix + 1

    ledger_account_id = None
    if payload.kind == "GENERAL":
        # Each general category posts to its own 62xx expense account (DECISION D-27).
        parent_id, account_code = _next_child_code(conn, "GENERAL_EXPENSES")
        ledger_account_id = conn.execute(
            _INSERT_LEDGER_ACCOUNT,
            {
                "code": account_code,
                "parent_id": parent_id,
                "name_ar": payload.name_ar,
                "name_en": payload.name_en,
                "type": "EXPENSE",
                "normal_side": "DEBIT",
                "subledger": "NONE",
            },
        ).scalar_one()

    new_id = conn.execute(
        text(
            """
            insert into public.expense_categories (tenant_id, kind, code, name_ar, name_en, ledger_account_id)
            values (private.current_tenant_id(), :kind, :code, :name_ar, :name_en, :ledger_account_id)
            returning id
            """
        ),
        {**payload.model_dump(), "code": code, "ledger_account_id": ledger_account_id},
    ).scalar_one()
    return _get_category(conn, new_id)


def _letters(number: int) -> str:
    """2 -> 'b', 3 -> 'c'... category codes are lowercase letters and underscores only."""
    letters = ""
    while number > 0:
        number, remainder = divmod(number - 1, 26)
        letters = chr(ord("a") + remainder) + letters
    return letters


def update_category(conn: Connection, category_id: UUID, changes: ExpenseCategoryUpdate) -> ExpenseCategoryOut:
    _get_category(conn, category_id)
    values = changes.model_dump(exclude_unset=True, exclude={"archived"})
    if changes.archived is not None:
        conn.execute(
            text(
                "update public.expense_categories set archived_at = case when :archived then now() end where id = :id"
            ),
            {"archived": changes.archived, "id": category_id},
        )
    if values:
        assignments = ", ".join(f"{column} = :{column}" for column in values)
        conn.execute(
            text(f"update public.expense_categories set {assignments} where id = :id"),  # noqa: S608
            {**values, "id": category_id},
        )
        conn.execute(
            text(
                """
                update public.ledger_accounts la set name_ar = ec.name_ar, name_en = ec.name_en
                  from public.expense_categories ec
                 where ec.id = :id and la.id = ec.ledger_account_id and not la.is_system
                """
            ),
            {"id": category_id},
        )
    return _get_category(conn, category_id)


def list_payment_methods(conn: Connection) -> list[PaymentMethodOut]:
    rows = conn.execute(
        text(
            "select id, code, name_ar, name_en, default_cash_account_id from public.payment_methods "
            "where archived_at is null order by sort_order"
        )
    ).mappings()
    return [PaymentMethodOut.model_validate(dict(row)) for row in rows]


# --- Previews ----------------------------------------------------------------------------------


def _preview_lines(conn: Connection, draft: EntryDraft) -> list[PreviewLine]:
    accounts = {
        row.id: row
        for row in conn.execute(
            text("select id, code, name_ar, name_en from public.ledger_accounts where id = any(:ids)"),
            {"ids": [line.account.ledger_account_id for line in draft.lines]},
        )
    }
    lines = []
    for line in draft.lines:
        account = accounts[line.account.ledger_account_id]
        lines.append(
            PreviewLine(
                account_code=account.code,
                account_name_ar=account.name_ar,
                account_name_en=account.name_en,
                debit=line.debit,
                credit=line.credit,
            )
        )
    return lines


def _money_texts(amount: Decimal, info: TenantInfo) -> tuple[str, str]:
    return format_money(amount, info.currency, "ar"), format_money(amount, info.currency, "en")


# --- General expenses (rule 20) ---------------------------------------------------------------------


@dataclass(frozen=True)
class _ExpensePlan:
    draft: EntryDraft
    category: Any
    cash: _ActiveCashAccount


def _plan_expense(conn: Connection, info: TenantInfo, payload: GeneralExpenseIn) -> _ExpensePlan:
    check_entry_date(info, payload.expense_date)
    category = conn.execute(
        text(
            "select id, kind, name_ar, name_en, ledger_account_id from public.expense_categories "
            "where id = :id and archived_at is null"
        ),
        {"id": payload.category_id},
    ).first()
    if category is None or category.kind != "GENERAL":
        raise AppError("CATEGORY_INVALID", "Choose an active general expense category", status_code=422)
    cash = _active_cash_account(conn, payload.cash_account_id)
    draft = rules.general_expense(
        entry_date=payload.expense_date,
        amount=payload.amount,
        expense_account=Account.by_id(category.ledger_account_id),
        paid_from=cash.ref,
        description=payload.description or category.name_ar,
        source_id=None,
    )
    return _ExpensePlan(draft=draft, category=category, cash=cash)


def preview_expense(conn: Connection, payload: GeneralExpenseIn, *, with_lines: bool) -> Preview:
    info = tenant_info(conn)
    plan = _plan_expense(conn, info, payload)
    ensure_period_open(conn, payload.expense_date)
    warnings = check_cash(conn, info, plan.draft.cash_effects(), lock=False)
    amount_ar, amount_en = _money_texts(payload.amount, info)
    return Preview(
        summary_ar=(
            f"سيتم خصم {amount_ar} من «{plan.cash.name_ar}» وتسجيلها كمصروف «{plan.category.name_ar}» "
            f"بتاريخ {ltr(payload.expense_date.isoformat())}."
        ),
        summary_en=(
            f"{amount_en} will be paid from “{plan.cash.name_en}” and recorded as a “{plan.category.name_en}” "
            f"expense on {payload.expense_date.isoformat()}."
        ),
        effects=[
            PreviewEffect(
                direction="OUT", label_ar=plan.cash.name_ar, label_en=plan.cash.name_en, amount=payload.amount
            ),
        ],
        warnings=warnings,
        lines=_preview_lines(conn, plan.draft) if with_lines else None,
    )


def record_expense(conn: Connection, payload: GeneralExpenseIn) -> PostingResult[GeneralExpenseOut]:
    info = tenant_info(conn)
    plan = _plan_expense(conn, info, payload)
    warnings = check_cash(conn, info, plan.draft.cash_effects(), lock=True)
    document_id = uuid4()
    posted = engine.post(conn, replace(plan.draft, source_id=document_id))
    conn.execute(
        text(
            """
            insert into public.general_expenses
              (id, tenant_id, expense_date, category_id, amount, description, cash_account_id, journal_entry_id)
            values
              (:id, private.current_tenant_id(), :expense_date, :category_id, :amount, :description,
               :cash_account_id, :journal_entry_id)
            """
        ),
        {**payload.model_dump(), "id": document_id, "journal_entry_id": posted.id},
    )
    return PostingResult[GeneralExpenseOut](
        document=get_expense(conn, document_id),
        journal_entries=[EntryRef(id=posted.id, entry_no=posted.entry_no)],
        warnings=warnings,
    )


_EXPENSES = """
    select ge.id, ge.expense_date, ge.category_id, ec.name_ar as category_name_ar, ec.name_en as category_name_en,
           ge.amount, ge.description, ge.cash_account_id, ca.name_ar as cash_account_name_ar,
           ca.name_en as cash_account_name_en, ge.status, je.entry_no, rje.entry_no as reversal_entry_no,
           ge.created_at
      from public.general_expenses ge
      join public.expense_categories ec on ec.id = ge.category_id
      join public.cash_accounts ca on ca.id = ge.cash_account_id
      join public.journal_entries je on je.id = ge.journal_entry_id
      left join public.journal_entries rje on rje.id = ge.reversal_entry_id
"""


def get_expense(conn: Connection, expense_id: UUID) -> GeneralExpenseOut:
    row = conn.execute(text(_EXPENSES + " where ge.id = :id"), {"id": expense_id}).mappings().first()
    if row is None:
        raise not_found("general expense")
    return GeneralExpenseOut.model_validate(dict(row))


def list_expenses(
    conn: Connection,
    *,
    date_from: date | None,
    date_to: date | None,
    category_id: UUID | None,
    page: int,
    page_size: int,
) -> Page[GeneralExpenseOut]:
    where = """
     where (cast(:date_from as date) is null or ge.expense_date >= :date_from)
       and (cast(:date_to as date) is null or ge.expense_date <= :date_to)
       and (cast(:category_id as uuid) is null or ge.category_id = :category_id)
    """
    params = {"date_from": date_from, "date_to": date_to, "category_id": category_id}
    total = conn.execute(text("select count(*) from public.general_expenses ge" + where), params).scalar_one()  # noqa: S608 - fixed SQL fragments, values are bound parameters
    rows = conn.execute(
        text(_EXPENSES + where + " order by ge.expense_date desc, je.entry_no desc limit :limit offset :offset"),
        {**params, "limit": page_size, "offset": (page - 1) * page_size},
    ).mappings()
    return Page[GeneralExpenseOut](
        items=[GeneralExpenseOut.model_validate(dict(row)) for row in rows],
        page=page,
        page_size=page_size,
        total=total,
    )


# --- Transfers (rule 21) ------------------------------------------------------------------------------


@dataclass(frozen=True)
class _TransferPlan:
    draft: EntryDraft
    source: _ActiveCashAccount
    destination: _ActiveCashAccount


def _plan_transfer(conn: Connection, info: TenantInfo, payload: TransferIn) -> _TransferPlan:
    check_entry_date(info, payload.transfer_date)
    if payload.from_cash_account_id == payload.to_cash_account_id:
        raise AppError("TRANSFER_SAME_ACCOUNT", "Choose two different accounts", status_code=422)
    source = _active_cash_account(conn, payload.from_cash_account_id)
    destination = _active_cash_account(conn, payload.to_cash_account_id)
    draft = rules.transfer(
        entry_date=payload.transfer_date,
        amount=payload.amount,
        source=source.ref,
        destination=destination.ref,
        description=payload.notes or f"تحويل من {source.name_ar} إلى {destination.name_ar}",
        source_id=None,
    )
    return _TransferPlan(draft=draft, source=source, destination=destination)


def preview_transfer(conn: Connection, payload: TransferIn, *, with_lines: bool) -> Preview:
    info = tenant_info(conn)
    plan = _plan_transfer(conn, info, payload)
    ensure_period_open(conn, payload.transfer_date)
    warnings = check_cash(conn, info, plan.draft.cash_effects(), lock=False)
    amount_ar, amount_en = _money_texts(payload.amount, info)
    return Preview(
        summary_ar=(
            f"سيتم تحويل {amount_ar} من «{plan.source.name_ar}» إلى «{plan.destination.name_ar}» "
            f"بتاريخ {ltr(payload.transfer_date.isoformat())}."
        ),
        summary_en=(
            f"{amount_en} will be moved from “{plan.source.name_en}” to “{plan.destination.name_en}” "
            f"on {payload.transfer_date.isoformat()}."
        ),
        effects=[
            PreviewEffect(
                direction="OUT",
                label_ar=plan.source.name_ar,
                label_en=plan.source.name_en,
                amount=payload.amount,
            ),
            PreviewEffect(
                direction="IN",
                label_ar=plan.destination.name_ar,
                label_en=plan.destination.name_en,
                amount=payload.amount,
            ),
        ],
        warnings=warnings,
        lines=_preview_lines(conn, plan.draft) if with_lines else None,
    )


def record_transfer(conn: Connection, payload: TransferIn) -> PostingResult[TransferOut]:
    info = tenant_info(conn)
    plan = _plan_transfer(conn, info, payload)
    warnings = check_cash(conn, info, plan.draft.cash_effects(), lock=True)
    document_id = uuid4()
    posted = engine.post(conn, replace(plan.draft, source_id=document_id))
    conn.execute(
        text(
            """
            insert into public.transfers
              (id, tenant_id, transfer_date, from_cash_account_id, to_cash_account_id, amount, notes, journal_entry_id)
            values
              (:id, private.current_tenant_id(), :transfer_date, :from_cash_account_id, :to_cash_account_id, :amount,
               :notes, :journal_entry_id)
            """
        ),
        {**payload.model_dump(), "id": document_id, "journal_entry_id": posted.id},
    )
    return PostingResult[TransferOut](
        document=get_transfer(conn, document_id),
        journal_entries=[EntryRef(id=posted.id, entry_no=posted.entry_no)],
        warnings=warnings,
    )


_TRANSFERS = """
    select tr.id, tr.transfer_date, tr.from_cash_account_id, fa.name_ar as from_name_ar, fa.name_en as from_name_en,
           tr.to_cash_account_id, ta.name_ar as to_name_ar, ta.name_en as to_name_en, tr.amount, tr.notes, tr.status,
           je.entry_no, rje.entry_no as reversal_entry_no, tr.created_at
      from public.transfers tr
      join public.cash_accounts fa on fa.id = tr.from_cash_account_id
      join public.cash_accounts ta on ta.id = tr.to_cash_account_id
      join public.journal_entries je on je.id = tr.journal_entry_id
      left join public.journal_entries rje on rje.id = tr.reversal_entry_id
"""


def get_transfer(conn: Connection, transfer_id: UUID) -> TransferOut:
    row = conn.execute(text(_TRANSFERS + " where tr.id = :id"), {"id": transfer_id}).mappings().first()
    if row is None:
        raise not_found("transfer")
    return TransferOut.model_validate(dict(row))


def list_transfers(
    conn: Connection, *, date_from: date | None, date_to: date | None, page: int, page_size: int
) -> Page[TransferOut]:
    where = """
     where (cast(:date_from as date) is null or tr.transfer_date >= :date_from)
       and (cast(:date_to as date) is null or tr.transfer_date <= :date_to)
    """
    params = {"date_from": date_from, "date_to": date_to}
    total = conn.execute(text("select count(*) from public.transfers tr" + where), params).scalar_one()  # noqa: S608 - fixed SQL fragments, values are bound parameters
    rows = conn.execute(
        text(_TRANSFERS + where + " order by tr.transfer_date desc, je.entry_no desc limit :limit offset :offset"),
        {**params, "limit": page_size, "offset": (page - 1) * page_size},
    ).mappings()
    return Page[TransferOut](
        items=[TransferOut.model_validate(dict(row)) for row in rows],
        page=page,
        page_size=page_size,
        total=total,
    )


# --- Cash book (SPEC §4.10, §4.12 #3) --------------------------------------------------------------------

_MOVEMENTS = text(
    """
    select e.entry_date, e.entry_no, e.description, e.source_type, l.debit, l.credit,
           e.reversal_of_id is not null as is_reversal, e.reversed_by_id is not null as reversed,
           coalesce((select string_agg(a.name_ar, '، ' order by o.line_no)
                       from public.journal_lines o join public.ledger_accounts a on a.id = o.ledger_account_id
                      where o.journal_entry_id = e.id and o.id <> l.id), '') as counterpart_ar,
           coalesce((select string_agg(a.name_en, ', ' order by o.line_no)
                       from public.journal_lines o join public.ledger_accounts a on a.id = o.ledger_account_id
                      where o.journal_entry_id = e.id and o.id <> l.id), '') as counterpart_en
      from public.journal_lines l
      join public.journal_entries e on e.id = l.journal_entry_id
     where l.cash_account_id = :id and l.entry_date between :date_from and :date_to
     order by l.entry_date, e.entry_no, l.line_no
    """
)


def cash_book(conn: Connection, cash_account_id: UUID, date_from: date, date_to: date) -> CashBookOut:
    if date_from > date_to:
        raise AppError("DATE_RANGE_INVALID", "The start date is after the end date", status_code=422)
    account = get_cash_account(conn, cash_account_id)
    info = tenant_info(conn)
    opening = Decimal(
        conn.execute(
            text(
                "select coalesce(sum(debit - credit), 0) from public.journal_lines "
                "where cash_account_id = :id and entry_date < :date_from"
            ),
            {"id": cash_account_id, "date_from": date_from},
        ).scalar_one()
    )
    balance, total_in, total_out = opening, ZERO, ZERO
    movements = []
    for row in conn.execute(_MOVEMENTS, {"id": cash_account_id, "date_from": date_from, "date_to": date_to}):
        balance += row.debit - row.credit
        total_in += row.debit
        total_out += row.credit
        movements.append(
            CashBookMovement(
                entry_date=row.entry_date,
                entry_no=row.entry_no,
                description=row.description,
                source_type=row.source_type,
                counterpart_ar=row.counterpart_ar,
                counterpart_en=row.counterpart_en,
                amount_in=row.debit,
                amount_out=row.credit,
                balance=balance,
                is_reversal=row.is_reversal,
                reversed=row.reversed,
            )
        )
    return CashBookOut(
        cash_account=account,
        date_from=date_from,
        date_to=date_to,
        currency_code=info.currency,
        opening_balance=opening,
        total_in=total_in,
        total_out=total_out,
        closing_balance=balance,
        movements=movements,
    )
