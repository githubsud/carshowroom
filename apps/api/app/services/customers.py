"""Customers (SPEC §4.6): buyers, sellers and consignors in one table (A-06).

Written only through the API (D-68): phone numbers are normalised to E.164
and national IDs encrypted here. Balances are derived from journal lines that
carry the customer id (deposits held, credit owed, deferred purchase prices).
"""

from dataclasses import replace
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import Connection, text

from app.core.crypto import FieldCipher, mask
from app.core.errors import AppError, not_found
from app.core.phone import normalize_phone, phone_digits
from app.domain.finance import EntryRef, Page, PostingResult, Preview, PreviewEffect
from app.domain.ledger import EntryDraft
from app.domain.money import format_money, ltr
from app.domain.vehicles import (
    CustomerBalances,
    CustomerDetail,
    CustomerHit,
    CustomerIn,
    CustomerOut,
    CustomerRefundIn,
    CustomerRefundOut,
    CustomerUpdate,
    SellerPayable,
)
from app.services import finance
from app.services.audit import record_event
from app.services.posting import engine, rules


def country_code(conn: Connection) -> str:
    code: str = conn.execute(
        text("select country_code from public.tenants where id = private.current_tenant_id()")
    ).scalar_one()
    return code


_CUSTOMERS = """
    select c.id, c.name, c.phone_primary, c.phones, c.national_id_last4, c.is_buyer, c.is_seller, c.is_consignor,
           c.address, c.notes, c.archived_at is not null as archived, c.created_at
      from public.customers c
"""


def _out(row: object) -> CustomerOut:
    data = dict(row._mapping)  # type: ignore[attr-defined]
    data["national_id_masked"] = mask(data.pop("national_id_last4"))
    return CustomerOut.model_validate(data)


def get_customer(conn: Connection, customer_id: UUID) -> CustomerOut:
    row = conn.execute(text(_CUSTOMERS + " where c.id = :id"), {"id": customer_id}).first()
    if row is None:
        raise not_found("customer")
    return _out(row)


def active_customer(conn: Connection, customer_id: UUID) -> CustomerOut:
    customer = conn.execute(text(_CUSTOMERS + " where c.id = :id"), {"id": customer_id}).first()
    if customer is None or customer.archived:
        raise AppError(
            "CUSTOMER_INVALID",
            "Unknown or archived customer",
            status_code=422,
            details={"customer_id": str(customer_id)},
        )
    return _out(customer)


_SEARCH = """
     where (cast(:archived as boolean) or c.archived_at is null)
       and (cast(:q as text) is null
            or c.name ilike '%' || :q || '%'
            or (:digits <> '' and (c.phone_primary like '%' || :digits || '%'
                                   or exists (select 1 from unnest(c.phones) p where p like '%' || :digits || '%'))))
       and (cast(:role as text) is null
            or (:role = 'BUYER' and c.is_buyer) or (:role = 'SELLER' and c.is_seller)
            or (:role = 'CONSIGNOR' and c.is_consignor))
"""


def list_customers(
    conn: Connection, *, q: str | None, role: str | None, include_archived: bool, page: int, page_size: int
) -> Page[CustomerOut]:
    query = q.strip() if q and q.strip() else None
    params = {
        "q": query,
        "digits": phone_digits(query) if query else "",
        "role": role,
        "archived": include_archived,
    }
    total = conn.execute(text("select count(*) from public.customers c" + _SEARCH), params).scalar_one()  # noqa: S608 - fixed SQL fragments, values are bound parameters
    rows = conn.execute(
        text(_CUSTOMERS + _SEARCH + " order by c.name limit :limit offset :offset"),
        {**params, "limit": page_size, "offset": (page - 1) * page_size},
    )
    return Page[CustomerOut](items=[_out(row) for row in rows], page=page, page_size=page_size, total=total)


def search(conn: Connection, q: str, limit: int = 5) -> list[CustomerHit]:
    rows = conn.execute(
        text(
            "select c.id, c.name, c.phone_primary from public.customers c"  # noqa: S608 - fixed SQL fragments
            + _SEARCH
            + " order by c.name limit :limit"
        ),
        {"q": q, "digits": phone_digits(q), "role": None, "archived": False, "limit": limit},
    ).mappings()
    return [CustomerHit.model_validate(dict(row)) for row in rows]


def _check_phone_free(conn: Connection, phone: str | None, own_id: UUID | None) -> None:
    if phone is None:
        return
    existing = conn.execute(
        text(
            "select id, name from public.customers where phone_primary = :phone and archived_at is null "
            "and (cast(:own as uuid) is null or id <> :own)"
        ),
        {"phone": phone, "own": own_id},
    ).first()
    if existing is not None:
        # Phone-first: the same person should not be entered twice.
        raise AppError(
            "CUSTOMER_PHONE_EXISTS",
            "A customer with this phone number already exists",
            status_code=409,
            details={"customer_id": str(existing.id), "name": existing.name},
        )


def _national_id_columns(cipher: FieldCipher, customer_id: UUID, national_id: str) -> dict[str, str]:
    return {
        "national_id_enc": cipher.encrypt(national_id, context=f"customer:{customer_id}"),
        "national_id_last4": national_id[-4:],
    }


def create_customer(conn: Connection, payload: CustomerIn, cipher: FieldCipher) -> CustomerOut:
    country = country_code(conn)
    phone = normalize_phone(payload.phone, country) if payload.phone else None
    others = [normalize_phone(item, country) for item in payload.other_phones]
    _check_phone_free(conn, phone, None)
    customer_id = uuid4()
    values: dict[str, object] = {
        "id": customer_id,
        "name": payload.name,
        "phone_primary": phone,
        "phones": [p for p in dict.fromkeys(others) if p != phone],
        "is_buyer": payload.is_buyer,
        "is_seller": payload.is_seller,
        "address": payload.address,
        "notes": payload.notes,
        "national_id_enc": None,
        "national_id_last4": None,
    }
    if payload.national_id:
        values.update(_national_id_columns(cipher, customer_id, payload.national_id))
    conn.execute(
        text(
            """
            insert into public.customers
              (id, tenant_id, name, phone_primary, phones, is_buyer, is_seller, address, notes, national_id_enc,
               national_id_last4)
            values (:id, private.current_tenant_id(), :name, :phone_primary, :phones, :is_buyer, :is_seller, :address,
                    :notes, :national_id_enc, :national_id_last4)
            """
        ),
        values,
    )
    return get_customer(conn, customer_id)


def update_customer(conn: Connection, customer_id: UUID, changes: CustomerUpdate, cipher: FieldCipher) -> CustomerOut:
    get_customer(conn, customer_id)
    country = country_code(conn)
    values: dict[str, object] = changes.model_dump(
        exclude_unset=True, exclude={"archived", "national_id", "phone", "other_phones"}
    )
    if "phone" in changes.model_fields_set:
        values["phone_primary"] = normalize_phone(changes.phone, country) if changes.phone else None
        _check_phone_free(conn, values["phone_primary"], customer_id)  # type: ignore[arg-type]
    if changes.other_phones is not None:
        values["phones"] = list(dict.fromkeys(normalize_phone(item, country) for item in changes.other_phones))
    if changes.national_id:
        values.update(_national_id_columns(cipher, customer_id, changes.national_id))
    if changes.archived is not None:
        conn.execute(
            text("update public.customers set archived_at = case when :archived then now() end where id = :id"),
            {"archived": changes.archived, "id": customer_id},
        )
    if values:
        assignments = ", ".join(f"{column} = :{column}" for column in values)  # keys from a StrictModel
        conn.execute(
            text(f"update public.customers set {assignments} where id = :id"),  # noqa: S608
            {**values, "id": customer_id},
        )
    return get_customer(conn, customer_id)


def flag(conn: Connection, customer_id: UUID, *, buyer: bool = False, seller: bool = False) -> None:
    conn.execute(
        text(
            "update public.customers set is_buyer = is_buyer or :buyer, is_seller = is_seller or :seller "
            "where id = :id and (not is_buyer and :buyer or not is_seller and :seller)"
        ),
        {"id": customer_id, "buyer": buyer, "seller": seller},
    )


def reveal_national_id(
    conn: Connection, customer_id: UUID, cipher: FieldCipher, *, actor: UUID, tenant_id: UUID
) -> str:
    token = conn.execute(
        text("select national_id_enc from public.customers where id = :id"), {"id": customer_id}
    ).scalar_one_or_none()
    if token is None:
        raise not_found("national id")
    value = cipher.decrypt(token, context=f"customer:{customer_id}")
    record_event(
        conn,
        tenant_id=tenant_id,
        actor=actor,
        action="NATIONAL_ID_VIEWED",
        entity_type="customers",
        entity_id=str(customer_id),
    )
    return value


# --- Balances ---------------------------------------------------------------------------------------


def _customer_balance(conn: Connection, customer_id: UUID, system_key: str) -> Decimal:
    return Decimal(
        conn.execute(
            text(
                """
                select coalesce(sum(l.credit - l.debit), 0)
                  from public.journal_lines l join public.ledger_accounts a on a.id = l.ledger_account_id
                 where l.customer_id = :id and a.system_key = :key
                """
            ),
            {"id": customer_id, "key": system_key},
        ).scalar_one()
    )


def credit_owed(conn: Connection, customer_id: UUID) -> Decimal:
    return _customer_balance(conn, customer_id, "CUSTOMER_CREDITS")


def seller_payables(conn: Connection, customer_id: UUID) -> list[SellerPayable]:
    rows = conn.execute(
        text(
            """
            select v.id as vehicle_id, v.stock_no, concat_ws(' ', v.make, v.model, v.year) as vehicle_label,
                   sum(l.credit - l.debit) as outstanding
              from public.journal_lines l
              join public.ledger_accounts a on a.id = l.ledger_account_id
              join public.vehicles v on v.id = l.vehicle_id
             where l.customer_id = :id and a.system_key = 'SELLER_PAYABLE'
             group by v.id
            having sum(l.credit - l.debit) <> 0
             order by v.stock_no
            """
        ),
        {"id": customer_id},
    ).mappings()
    return [SellerPayable.model_validate(dict(row)) for row in rows]


def detail(conn: Connection, customer_id: UUID, *, with_balances: bool, with_payables: bool) -> CustomerDetail:
    customer = get_customer(conn, customer_id)
    balances = None
    if with_balances:
        balances = CustomerBalances(
            deposits_held=_customer_balance(conn, customer_id, "CUSTOMER_DEPOSITS"),
            credit_owed=credit_owed(conn, customer_id),
        )
    return CustomerDetail(
        customer=customer,
        balances=balances,
        seller_payables=seller_payables(conn, customer_id) if with_payables else None,
    )


# --- Refund of customer credit (P-02 refund leg, D-41) --------------------------------------------------


def _plan_refund(
    conn: Connection, info: finance.TenantInfo, customer: CustomerOut, payload: CustomerRefundIn
) -> tuple[EntryDraft, finance.ActiveCashAccount]:
    finance.check_entry_date(info, payload.refund_date)
    owed = credit_owed(conn, customer.id)
    if payload.amount > owed:
        raise AppError(
            "REFUND_EXCEEDS_CREDIT",
            "The refund is more than the showroom owes the customer",
            status_code=422,
            details={"credit_owed": f"{owed:.2f}"},
        )
    cash = finance.active_cash_account(conn, payload.cash_account_id)
    draft = rules.customer_credit_refund(
        entry_date=payload.refund_date,
        customer_id=customer.id,
        amount=payload.amount,
        paid_from=cash.ref,
        description=payload.notes or f"رد مبلغ للعميل {customer.name}",
        source_id=None,
    )
    return draft, cash


def preview_refund(conn: Connection, customer_id: UUID, payload: CustomerRefundIn, *, with_lines: bool) -> Preview:
    info = finance.tenant_info(conn)
    customer = get_customer(conn, customer_id)
    draft, cash = _plan_refund(conn, info, customer, payload)
    finance.ensure_period_open(conn, payload.refund_date)
    warnings = finance.check_cash(conn, info, draft.cash_effects(), lock=False)
    amount_ar = format_money(payload.amount, info.currency, "ar")
    amount_en = format_money(payload.amount, info.currency, "en")
    return Preview(
        summary_ar=(
            f"سيتم صرف {amount_ar} من «{cash.name_ar}» للعميل {customer.name} من رصيده المستحق "
            f"بتاريخ {ltr(payload.refund_date.isoformat())}."
        ),
        summary_en=(
            f"{amount_en} will be paid from “{cash.name_en}” to {customer.name} out of the amount owed to them "
            f"on {payload.refund_date.isoformat()}."
        ),
        effects=[PreviewEffect(direction="OUT", label_ar=cash.name_ar, label_en=cash.name_en, amount=payload.amount)],
        warnings=warnings,
        lines=finance.preview_lines(conn, draft) if with_lines else None,
    )


def record_refund(conn: Connection, customer_id: UUID, payload: CustomerRefundIn) -> PostingResult[CustomerRefundOut]:
    info = finance.tenant_info(conn)
    conn.execute(text("select 1 from public.customers where id = :id for update"), {"id": customer_id})
    customer = get_customer(conn, customer_id)
    draft, _ = _plan_refund(conn, info, customer, payload)
    warnings = finance.check_cash(conn, info, draft.cash_effects(), lock=True)
    document_id = uuid4()
    posted = engine.post(conn, replace(draft, source_id=document_id))
    conn.execute(
        text(
            """
            insert into public.customer_refunds
              (id, tenant_id, customer_id, refund_date, amount, cash_account_id, notes, journal_entry_id)
            values (:id, private.current_tenant_id(), :customer_id, :refund_date, :amount, :cash_account_id, :notes,
                    :journal_entry_id)
            """
        ),
        {**payload.model_dump(), "id": document_id, "customer_id": customer_id, "journal_entry_id": posted.id},
    )
    return PostingResult[CustomerRefundOut](
        document=CustomerRefundOut(
            id=document_id,
            customer_id=customer_id,
            refund_date=payload.refund_date,
            amount=payload.amount,
            cash_account_id=payload.cash_account_id,
            status="POSTED",
            entry_no=posted.entry_no,
        ),
        journal_entries=[EntryRef(id=posted.id, entry_no=posted.entry_no)],
        warnings=warnings,
    )
