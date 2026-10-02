"""Phase 4 acceptance: the full purchase -> expenses -> sale cycle posts correctly
and the vehicle file shows exact cost and profit (SPEC §13), plus cost
masking for sales staff (SPEC §10) and the vehicle/sale business rules."""

import random
import uuid
from datetime import date
from decimal import Decimal
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Connection, text

from app.core.errors import AppError
from app.domain.finance import ReverseIn
from app.domain.sales import ReservationIn, ReservationSettleIn, SaleCancelIn, SaleDraftIn
from app.domain.vehicles import (
    CustomerIn,
    CustomerRefundIn,
    PurchaseIn,
    SellerPaymentIn,
    SupplierIn,
    SupplierPaymentIn,
    VehicleExpenseIn,
    VehicleIn,
)
from app.integrations.storage import DisabledStorage
from app.services import customers, finance, journal, sales, suppliers, vehicles
from tests.integration.conftest import DOHA, NOUR, auth

NOUR_CASH = uuid.UUID("c0000000-0000-0000-0000-000000000001")
NOUR_BANK = uuid.UUID("c0000000-0000-0000-0000-000000000002")
AHMED = uuid.UUID("f0000000-0000-0000-0000-000000000001")
OWNER_ID = uuid.UUID("a0000000-0000-0000-0000-000000000001")
DAY = date(2026, 10, 1)
FORBIDDEN_KEYS = {"cost", "total_cost", "cost_complete", "missing_categories", "profit", "purchase", "min_price"}


class _Rollback(Exception):
    """Raised on purpose so a scenario leaves no trace."""


def _phone() -> str:
    return f"010{random.randint(10_000_000, 99_999_999)}"  # noqa: S311 - test data


def _owner_tx(client: TestClient) -> Any:
    database = client.app.state.database  # type: ignore[attr-defined]
    return database.transaction(user_id=OWNER_ID, tenant_id=uuid.UUID(NOUR))


def _category(conn: Connection, code: str) -> uuid.UUID:
    return conn.execute(
        text("select id from public.expense_categories where kind = 'VEHICLE' and code = :code"), {"code": code}
    ).scalar_one()


def _customer(conn: Connection, name: str) -> uuid.UUID:
    return customers.create_customer(conn, CustomerIn(name=name, phone=_phone()), _NoCipher()).id  # type: ignore[arg-type]


class _NoCipher:
    def encrypt(self, plaintext: str, *, context: str) -> str:  # pragma: no cover - no national IDs here
        raise AssertionError("not used")


def _vehicle(conn: Connection, make: str = "Hyundai", model: str = "Elantra", year: int = 2019) -> uuid.UUID:
    return vehicles.create_vehicle(conn, VehicleIn(make=make, model=model, year=year, asking_price=Decimal(500000)))


def _expense(conn: Connection, vehicle_id: uuid.UUID, code: str, amount: str, **funding: Any) -> Any:
    payload = {"expense_date": DAY, "category_id": _category(conn, code), "amount": amount}
    payload.update(funding or {"funding": "CASH_ACCOUNT", "cash_account_id": NOUR_CASH})
    return vehicles.record_expense(conn, vehicle_id, VehicleExpenseIn.model_validate(payload))


def _balances(conn: Connection) -> tuple[Decimal, Decimal]:
    return finance.get_cash_account(conn, NOUR_CASH).balance, finance.get_cash_account(conn, NOUR_BANK).balance


# --- The hand-calculated cycle -----------------------------------------------------------------------


def test_purchase_expenses_sale_cycle_matches_hand_calculation(client: TestClient) -> None:
    """معرض النور, all on 2026-10-01 (EGP):

     6/7  buy Elantra 400,000: 300,000 by bank, 100,000 owed to Karim     cost 400,000
       9  paint 15,000 from the cash box                                  cost 415,000
      31  maintenance 12,000 on credit from Al-Amal garage                 cost 427,000
      30  transport 3,000 paid by partner Ahmed (current account)          cost 430,000
       8  pay Karim the 100,000 still owed, by bank
      11  Hassan reserves with a 20,000 cash deposit
      12  sold for 500,000 less 10,000 discount = 490,000: deposit 20,000 + bank 470,000
          cost of sales 430,000 -> profit 60,000 (12.24%)
    P-04  transport 1,200 in cash after the sale -> cost 431,200, profit 58,800 (12.00%)
      32  garage paid 12,000 in cash

    Cash box: -15,000 +20,000 -1,200 -12,000 = -8,200     Bank: -300,000 -100,000 +470,000 = +70,000
    """

    def scenario() -> None:
        with _owner_tx(client) as conn:
            cash_before, bank_before = _balances(conn)
            karim, hassan = _customer(conn, "كريم البائع"), _customer(conn, "حسن المشتري")
            garage = suppliers.create_supplier(conn, SupplierIn(name="ورشة الأمل", kind="WORKSHOP")).id
            car = _vehicle(conn)

            purchase = vehicles.record_purchase(
                conn,
                car,
                PurchaseIn.model_validate(
                    {
                        "seller_customer_id": karim,
                        "purchase_date": DAY,
                        "price": "400000",
                        "payments": [{"cash_account_id": NOUR_BANK, "amount": "300000"}],
                    }
                ),
            )
            assert purchase.document.deferred_amount == Decimal("100000.00")
            assert vehicles.vehicle_ref(conn, car).status == "IN_PREPARATION"
            assert vehicles.vehicle_ref(conn, car).stock_date == DAY

            _expense(conn, car, "paint", "15000")
            _expense(conn, car, "maintenance", "12000", funding="SUPPLIER_CREDIT", supplier_id=garage)
            _expense(
                conn,
                car,
                "transport",
                "3000",
                funding="PARTNER",
                paid_by_partner_id=AHMED,
                partner_funding_mode="CURRENT_ACCOUNT",
            )
            assert vehicles.inventory_cost(conn, car) == Decimal("430000.00")

            vehicles.record_seller_payment(
                conn,
                car,
                SellerPaymentIn.model_validate({"payment_date": DAY, "amount": "100000", "cash_account_id": NOUR_BANK}),
            )
            assert vehicles.purchase_summary(conn, car).outstanding == Decimal("0.00")  # type: ignore[union-attr]

            vehicles.change_status(conn, car, "AVAILABLE", None)
            reservation = sales.create_reservation(
                conn,
                ReservationIn.model_validate(
                    {
                        "vehicle_id": car,
                        "customer_id": hassan,
                        "reservation_date": DAY,
                        "deposit_amount": "20000",
                        "cash_account_id": NOUR_CASH,
                    }
                ),
            ).document
            assert vehicles.vehicle_ref(conn, car).status == "RESERVED"

            draft = sales.create_draft(
                conn,
                SaleDraftIn.model_validate(
                    {
                        "vehicle_id": car,
                        "buyer_customer_id": hassan,
                        "sale_date": DAY,
                        "list_price": "500000",
                        "discount": "10000",
                        "reservation_id": reservation.id,
                        "payments": [{"cash_account_id": NOUR_BANK, "amount": "470000"}],
                    }
                ),
                viewer_id=OWNER_ID,
                see_all_drafts=True,
                with_profit=True,
            )
            assert draft.remaining == Decimal("0.00")
            posted = sales.post_sale(conn, draft.id, user_id=OWNER_ID, with_profit=True)
            sale = posted.document
            assert sale.status == "POSTED"
            assert sale.invoice_no is not None
            assert sale.invoice_no.startswith("INV-2026-")
            assert sale.einvoice_status == "NOT_SUBMITTED"  # Egypt ETA stub (D-39)
            assert sale.profit is not None
            assert (sale.profit.cost, sale.profit.gross_profit, sale.profit.profit_pct) == (
                Decimal("430000.00"),
                Decimal("60000.00"),
                Decimal("12.24"),
            )
            assert vehicles.vehicle_ref(conn, car).status == "SOLD"
            assert sales.get_reservation(conn, reservation.id).status == "APPLIED"

            # P-04: a late invoice on a sold car goes to cost of sales.
            late = _expense(conn, car, "transport", "1200")
            assert late.document.treatment == "COGS"

            garage_balance = suppliers.get_supplier(conn, garage).balance
            assert garage_balance == Decimal("12000.00")
            suppliers.record_payment(
                conn,
                garage,
                SupplierPaymentIn.model_validate(
                    {"payment_date": DAY, "amount": "12000", "cash_account_id": NOUR_CASH}
                ),
            )
            assert suppliers.get_supplier(conn, garage).balance == Decimal("0.00")

            detail = vehicles.get_detail(conn, car, DisabledStorage(), can_view_cost=True)
            assert detail.cost is not None
            assert detail.profit is not None
            assert detail.cost.total_cost == Decimal("431200.00")
            assert [line.amount for line in detail.cost.lines] == [
                Decimal("400000.00"),
                Decimal("15000.00"),
                Decimal("12000.00"),
                Decimal("3000.00"),
                Decimal("1200.00"),
            ]
            assert (detail.profit.sale_price, detail.profit.gross_profit, detail.profit.profit_pct) == (
                Decimal("490000.00"),
                Decimal("58800.00"),
                Decimal("12.00"),
            )
            assert detail.sale is not None
            assert detail.sale.buyer_name == "حسن المشتري"

            cash_after, bank_after = _balances(conn)
            assert cash_after - cash_before == Decimal("-8200.00")
            assert bank_after - bank_before == Decimal("70000.00")

            # Business rule 1: the same car cannot be sold again.
            second = sales.create_draft(
                conn,
                SaleDraftIn.model_validate(
                    {
                        "vehicle_id": car,
                        "buyer_customer_id": karim,
                        "sale_date": DAY,
                        "list_price": "1000",
                        "payments": [{"cash_account_id": NOUR_CASH, "amount": "1000"}],
                    }
                ),
                viewer_id=OWNER_ID,
                see_all_drafts=True,
                with_profit=True,
            )
            with pytest.raises(AppError) as sold_twice:
                sales.post_sale(conn, second.id, user_id=OWNER_ID, with_profit=True)
            assert sold_twice.value.code == "VEHICLE_ALREADY_SOLD"
            raise _Rollback

    with pytest.raises(_Rollback):
        scenario()


def test_trade_in_profit_and_cancellation_to_customer_credit(client: TestClient) -> None:
    """Rule 26 then P-03 (the default cancellation method, D-41):
    V6 costs 450,000 and is sold to Omar for 550,000: his own car is taken at
    200,000 and 350,000 comes by bank. Profit 100,000; the trade-in car's cost
    file starts at 200,000. Cancelling returns V6 to stock at 450,000, hands the
    trade-in car back, and leaves 350,000 owed to Omar until it is refunded."""

    def scenario() -> None:
        with _owner_tx(client) as conn:
            cash_before, bank_before = _balances(conn)
            seller, omar = _customer(conn, "بائع"), _customer(conn, "عمر")
            car = _vehicle(conn, "Kia", "Sportage", 2021)
            vehicles.record_purchase(
                conn,
                car,
                PurchaseIn.model_validate(
                    {
                        "seller_customer_id": seller,
                        "purchase_date": DAY,
                        "price": "450000",
                        "payments": [{"cash_account_id": NOUR_BANK, "amount": "450000"}],
                        "ready_for_sale": True,
                    }
                ),
            )
            draft = sales.create_draft(
                conn,
                SaleDraftIn.model_validate(
                    {
                        "vehicle_id": car,
                        "buyer_customer_id": omar,
                        "sale_date": DAY,
                        "list_price": "550000",
                        "payments": [{"cash_account_id": NOUR_BANK, "amount": "350000"}],
                        "trade_in": {"make": "Toyota", "model": "Corolla", "year": 2015, "agreed_value": "200000"},
                    }
                ),
                viewer_id=OWNER_ID,
                see_all_drafts=True,
                with_profit=True,
            )
            sale = sales.post_sale(conn, draft.id, user_id=OWNER_ID, with_profit=True).document
            assert sale.profit is not None
            assert sale.profit.gross_profit == Decimal("100000.00")
            trade_in = sale.trade_in_vehicle_id
            assert trade_in is not None
            trade_detail = vehicles.get_detail(conn, trade_in, DisabledStorage(), can_view_cost=True)
            assert (trade_detail.status, trade_detail.acquisition_source) == ("IN_PREPARATION", "TRADE_IN")
            assert trade_detail.cost is not None
            assert trade_detail.cost.total_cost == Decimal("200000.00")
            assert trade_detail.purchase is not None
            assert trade_detail.purchase.seller_name == "عمر"

            cancelled = sales.cancel_sale(
                conn, sale.id, SaleCancelIn(reason="العميل تراجع"), user_id=OWNER_ID, with_profit=True
            ).document
            assert (cancelled.status, cancelled.cancellation_method) == ("CANCELLED", "REFUND_LIABILITY")
            assert vehicles.vehicle_ref(conn, car).status == "AVAILABLE"
            assert vehicles.inventory_cost(conn, car) == Decimal("450000.00")
            assert vehicles.vehicle_ref(conn, trade_in).status == "ARCHIVED"
            assert vehicles.inventory_cost(conn, trade_in) == Decimal("0.00")
            assert customers.credit_owed(conn, omar) == Decimal("350000.00")
            # No money moved yet: the refund is separate (C-06).
            assert _balances(conn) == (cash_before, bank_before - Decimal("100000.00"))

            customers.record_refund(
                conn,
                omar,
                CustomerRefundIn.model_validate({"refund_date": DAY, "amount": "350000", "cash_account_id": NOUR_BANK}),
            )
            assert customers.credit_owed(conn, omar) == Decimal("0.00")
            assert _balances(conn) == (cash_before, bank_before - Decimal("450000.00"))

            # The car can be sold again after the cancellation.
            again = sales.create_draft(
                conn,
                SaleDraftIn.model_validate(
                    {
                        "vehicle_id": car,
                        "buyer_customer_id": seller,
                        "sale_date": DAY,
                        "list_price": "500000",
                        "payments": [{"cash_account_id": NOUR_CASH, "amount": "500000"}],
                    }
                ),
                viewer_id=OWNER_ID,
                see_all_drafts=True,
                with_profit=True,
            )
            resold = sales.post_sale(conn, again.id, user_id=OWNER_ID, with_profit=True).document
            assert resold.profit is not None
            assert resold.profit.gross_profit == Decimal("50000.00")
            raise _Rollback

    with pytest.raises(_Rollback):
        scenario()


def test_mirror_cancellation_puts_the_deposit_back_on_hold(client: TestClient) -> None:
    """MIRROR (literal rule 33): the exact opposite of the sale entries on the
    cancellation date. The bank is credited back at once, and the deposit is
    held again until it is refunded (rule 34) or forfeited (rule 35)."""

    def scenario() -> None:
        with _owner_tx(client) as conn:
            conn.execute(text("update public.tenant_settings set sale_cancellation_method = 'MIRROR'"))
            cash_before, bank_before = _balances(conn)
            seller, buyer = _customer(conn, "بائع"), _customer(conn, "مشتري")
            car = _vehicle(conn, "Nissan", "Sunny", 2020)
            vehicles.record_purchase(
                conn,
                car,
                PurchaseIn.model_validate(
                    {
                        "seller_customer_id": seller,
                        "purchase_date": DAY,
                        "price": "200000",
                        "payments": [{"cash_account_id": NOUR_BANK, "amount": "200000"}],
                        "ready_for_sale": True,
                    }
                ),
            )
            reservation = sales.create_reservation(
                conn,
                ReservationIn.model_validate(
                    {
                        "vehicle_id": car,
                        "customer_id": buyer,
                        "reservation_date": DAY,
                        "deposit_amount": "5000",
                        "cash_account_id": NOUR_CASH,
                    }
                ),
            ).document
            draft = sales.create_draft(
                conn,
                SaleDraftIn.model_validate(
                    {
                        "vehicle_id": car,
                        "buyer_customer_id": buyer,
                        "sale_date": DAY,
                        "list_price": "240000",
                        "reservation_id": reservation.id,
                        "payments": [{"cash_account_id": NOUR_BANK, "amount": "235000"}],
                    }
                ),
                viewer_id=OWNER_ID,
                see_all_drafts=True,
                with_profit=True,
            )
            sale = sales.post_sale(conn, draft.id, user_id=OWNER_ID, with_profit=True).document
            sales.cancel_sale(conn, sale.id, SaleCancelIn(reason="خطأ في التسجيل"), user_id=OWNER_ID, with_profit=True)

            assert vehicles.vehicle_ref(conn, car).status == "AVAILABLE"
            assert vehicles.inventory_cost(conn, car) == Decimal("200000.00")
            assert sales.get_reservation(conn, reservation.id).status == "RELEASED"
            assert _balances(conn) == (cash_before + Decimal("5000.00"), bank_before - Decimal("200000.00"))
            entries = conn.execute(
                text(
                    "select count(*) from public.journal_entries where source_id = :id and reversed_by_id is not null"
                ),
                {"id": sale.id},
            ).scalar_one()
            assert entries == 2  # sale and cost entries are mirrored and linked

            sales.settle_reservation(conn, reservation.id, ReservationSettleIn(action="FORFEIT", settle_date=DAY))
            assert sales.get_reservation(conn, reservation.id).status == "FORFEITED"
            assert vehicles.vehicle_ref(conn, car).status == "AVAILABLE"
            raise _Rollback

    with pytest.raises(_Rollback):
        scenario()


def test_deposit_refund_frees_the_car(client: TestClient) -> None:
    def scenario() -> None:
        with _owner_tx(client) as conn:
            seller, buyer = _customer(conn, "بائع"), _customer(conn, "حاجز")
            car = _vehicle(conn)
            vehicles.record_purchase(
                conn,
                car,
                PurchaseIn.model_validate(
                    {"seller_customer_id": seller, "purchase_date": DAY, "price": "100000", "ready_for_sale": True}
                ),
            )
            cash_before = _balances(conn)[0]
            reservation = sales.create_reservation(
                conn,
                ReservationIn.model_validate(
                    {
                        "vehicle_id": car,
                        "customer_id": buyer,
                        "reservation_date": DAY,
                        "deposit_amount": "3000",
                        "cash_account_id": NOUR_CASH,
                        "expires_on": "2026-10-01",
                    }
                ),
            ).document
            assert reservation.expired is True  # the expiry date has passed (today is later)
            sales.settle_reservation(
                conn,
                reservation.id,
                ReservationSettleIn(action="REFUND", settle_date=DAY, cash_account_id=NOUR_CASH),
            )
            assert vehicles.vehicle_ref(conn, car).status == "AVAILABLE"
            assert _balances(conn)[0] == cash_before
            raise _Rollback

    with pytest.raises(_Rollback):
        scenario()


def test_cost_checklist_marks_profit_as_an_estimate(client: TestClient) -> None:
    def scenario() -> None:
        with _owner_tx(client) as conn:
            conn.execute(text("update public.tenant_settings set expected_cost_categories = '{inspection,transport}'"))
            seller = _customer(conn, "بائع")
            car = _vehicle(conn)
            vehicles.record_purchase(
                conn,
                car,
                PurchaseIn.model_validate({"seller_customer_id": seller, "purchase_date": DAY, "price": "1000"}),
            )
            _expense(conn, car, "inspection", "100")
            detail = vehicles.get_detail(conn, car, DisabledStorage(), can_view_cost=True)
            assert detail.cost is not None
            assert (detail.cost.cost_complete, detail.cost.missing_categories) == (False, ["نقل"])
            raise _Rollback

    with pytest.raises(_Rollback):
        scenario()


def test_sale_entries_are_undone_only_by_cancelling(client: TestClient) -> None:
    def scenario() -> None:
        with _owner_tx(client) as conn:
            seller, buyer = _customer(conn, "بائع"), _customer(conn, "مشتري")
            car = _vehicle(conn)
            purchase = vehicles.record_purchase(
                conn,
                car,
                PurchaseIn.model_validate(
                    {"seller_customer_id": seller, "purchase_date": DAY, "price": "1000", "ready_for_sale": True}
                ),
            )
            draft = sales.create_draft(
                conn,
                SaleDraftIn.model_validate(
                    {
                        "vehicle_id": car,
                        "buyer_customer_id": buyer,
                        "sale_date": DAY,
                        "list_price": "1500",
                        "payments": [{"cash_account_id": NOUR_CASH, "amount": "1500"}],
                    }
                ),
                viewer_id=OWNER_ID,
                see_all_drafts=True,
                with_profit=True,
            )
            posted = sales.post_sale(conn, draft.id, user_id=OWNER_ID, with_profit=True)
            for entry, code in (
                (posted.journal_entries[0].id, "USE_DOCUMENT_ACTION"),
                (purchase.journal_entries[0].id, "VEHICLE_ALREADY_SOLD"),
            ):
                with pytest.raises(AppError) as refused:
                    journal.reverse(conn, entry, ReverseIn(reason="تجربة الإلغاء"))
                assert refused.value.code == code
            raise _Rollback

    with pytest.raises(_Rollback):
        scenario()


# --- Through the API ----------------------------------------------------------------------------------------


def _headers(email: str, tenant: str = NOUR) -> dict[str, str]:
    return {**auth(email, tenant), "Idempotency-Key": str(uuid.uuid4())}


OWNER = "owner@nour.example"
SALES = "sales@nour.example"
ACCOUNTANT = "accountant@nour.example"


@pytest.fixture
def sold_car(client: TestClient) -> dict[str, str]:
    """A car bought, expensed and sold through the API (committed, unique per run)."""
    seller = client.post(
        "/api/v1/customers", headers=_headers(OWNER), json={"name": "بائع API", "phone": _phone()}
    ).json()["id"]
    buyer = client.post(
        "/api/v1/customers", headers=_headers(OWNER), json={"name": "مشتري API", "phone": _phone()}
    ).json()["id"]
    car = client.post(
        "/api/v1/vehicles",
        headers=_headers(OWNER),
        json={"make": "Mazda", "model": "3", "year": 2018, "asking_price": "300000", "min_price": "280000"},
    ).json()["id"]
    response = client.post(
        f"/api/v1/vehicles/{car}/purchase",
        headers=_headers(OWNER),
        json={
            "seller_customer_id": seller,
            "purchase_date": "2026-10-01",
            "price": "250000",
            "payments": [{"cash_account_id": str(NOUR_BANK), "amount": "250000"}],
            "ready_for_sale": True,
        },
    )
    assert response.status_code == 201, response.text
    with _no_db_client(client) as conn:
        paint = _category(conn, "paint")
    response = client.post(
        f"/api/v1/vehicles/{car}/expenses",
        headers=_headers(OWNER),
        json={
            "expense_date": "2026-10-01",
            "category_id": str(paint),
            "amount": "5000",
            "cash_account_id": str(NOUR_CASH),
        },
    )
    assert response.status_code == 201, response.text
    draft = client.post(
        "/api/v1/sales",
        headers=_headers(SALES),
        json={
            "vehicle_id": car,
            "buyer_customer_id": buyer,
            "sale_date": "2026-10-01",
            "list_price": "300000",
            "payments": [{"cash_account_id": str(NOUR_BANK), "amount": "300000"}],
        },
    )
    assert draft.status_code == 201, draft.text
    sale = draft.json()["id"]
    assert client.post(f"/api/v1/sales/{sale}/post", headers=_headers(SALES)).status_code == 403
    posted = client.post(f"/api/v1/sales/{sale}/post", headers=_headers(ACCOUNTANT))
    assert posted.status_code == 201, posted.text
    return {"vehicle": car, "sale": sale, "buyer": buyer, "seller": seller}


def _no_db_client(client: TestClient) -> Any:
    return _owner_tx(client)


def _keys(value: Any) -> set[str]:
    if isinstance(value, dict):
        return set(value) | {key for item in value.values() for key in _keys(item)}
    if isinstance(value, list):
        return {key for item in value for key in _keys(item)}
    return set()


def test_sales_staff_never_receive_cost_data(client: TestClient, sold_car: dict[str, str]) -> None:
    owner_view = client.get(f"/api/v1/vehicles/{sold_car['vehicle']}", headers=auth(OWNER, NOUR)).json()
    assert owner_view["cost"]["total_cost"] == "255000.00"
    assert owner_view["profit"]["gross_profit"] == "45000.00"
    assert owner_view["min_price"] == "280000.00"

    responses = [
        client.get(f"/api/v1/vehicles/{sold_car['vehicle']}", headers=auth(SALES, NOUR)),
        client.get("/api/v1/vehicles?page_size=100", headers=auth(SALES, NOUR)),
        client.get("/api/v1/search?q=Mazda", headers=auth(SALES, NOUR)),
        client.get(f"/api/v1/sales/{sold_car['sale']}", headers=auth(SALES, NOUR)),
        client.get(f"/api/v1/customers/{sold_car['seller']}", headers=auth(SALES, NOUR)),
        client.get(f"/api/v1/documents?entity_type=VEHICLE&entity_id={sold_car['vehicle']}", headers=auth(SALES, NOUR)),
    ]
    for response in responses:
        assert response.status_code == 200, response.text
        assert not (_keys(response.json()) & FORBIDDEN_KEYS), response.url
    assert client.get(f"/api/v1/vehicles/{sold_car['vehicle']}/expenses", headers=auth(SALES, NOUR)).status_code == 403
    sale = responses[3].json()
    assert sale["sale_price"] == "300000.00"
    assert sale["status"] == "POSTED"


def test_sales_staff_cannot_buy_or_spend(client: TestClient, sold_car: dict[str, str]) -> None:
    car = sold_car["vehicle"]
    purchase = client.post(
        f"/api/v1/vehicles/{car}/purchase/preview",
        headers=_headers(SALES),
        json={"seller_customer_id": sold_car["seller"], "purchase_date": "2026-10-01", "price": "1"},
    )
    assert purchase.status_code == 403
    min_price = client.patch(f"/api/v1/vehicles/{car}", headers=_headers(SALES), json={"min_price": "1"})
    assert min_price.status_code == 403


def test_vehicle_rules_through_the_api(client: TestClient, sold_car: dict[str, str]) -> None:
    car = sold_car["vehicle"]
    # Manual moves follow the lifecycle; SOLD -> AVAILABLE only by cancelling the sale.
    invalid = client.post(f"/api/v1/vehicles/{car}/status", headers=_headers(OWNER), json={"status": "AVAILABLE"})
    assert invalid.status_code == 409
    assert invalid.json()["error"]["code"] == "VEHICLE_INVALID_TRANSITION"

    delivered = client.post(f"/api/v1/vehicles/{car}/status", headers=_headers(OWNER), json={"status": "DELIVERED"})
    assert delivered.status_code == 200, delivered.text
    assert delivered.json()["location_name_en"] == "With customer"
    cancel = client.post(
        f"/api/v1/sales/{sold_car['sale']}/cancel/preview", headers=_headers(OWNER), json={"reason": "تجربة"}
    )
    assert cancel.json()["error"]["code"] == "SALE_DELIVERED"


def test_vin_must_be_unique_in_stock(client: TestClient) -> None:
    vin = f"JTDBR32E{random.randint(100000000, 999999999)}"  # noqa: S311 - test data
    first = client.post(
        "/api/v1/vehicles", headers=_headers(OWNER), json={"make": "Toyota", "model": "Yaris", "vin": vin}
    )
    assert first.status_code == 201
    assert first.json()["stock_no"].startswith("V-")
    again = client.post(
        "/api/v1/vehicles", headers=_headers(OWNER), json={"make": "Toyota", "model": "Yaris", "vin": vin.lower()}
    )
    assert again.status_code == 409
    assert again.json()["error"]["code"] == "VEHICLE_VIN_DUPLICATE"


def test_sale_needs_matching_amounts_and_a_recorded_cost(client: TestClient) -> None:
    buyer = client.post("/api/v1/customers", headers=_headers(OWNER), json={"name": "x", "phone": _phone()}).json()[
        "id"
    ]
    car = client.post("/api/v1/vehicles", headers=_headers(OWNER), json={"make": "Kia", "model": "Rio"}).json()["id"]
    draft = client.post(
        "/api/v1/sales",
        headers=_headers(OWNER),
        json={
            "vehicle_id": car,
            "buyer_customer_id": buyer,
            "sale_date": "2026-10-01",
            "list_price": "100000",
            "payments": [{"cash_account_id": str(NOUR_CASH), "amount": "60000"}],
        },
    ).json()
    assert draft["remaining"] == "40000.00"
    preview = client.post(f"/api/v1/sales/{draft['id']}/post/preview", headers=_headers(OWNER))
    assert preview.json()["error"]["code"] == "VEHICLE_NOT_AVAILABLE"
    assert client.delete(f"/api/v1/sales/{draft['id']}", headers=_headers(OWNER)).status_code == 204


def test_customer_phone_is_normalised_and_unique(client: TestClient) -> None:
    raw = _phone()
    created = client.post("/api/v1/customers", headers=_headers(SALES), json={"name": "عميل", "phone": raw})
    assert created.status_code == 201
    assert created.json()["phone_primary"] == "+20" + raw[1:]
    duplicate = client.post("/api/v1/customers", headers=_headers(SALES), json={"name": "مكرر", "phone": raw})
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["details"]["customer_id"] == created.json()["id"]
    found = client.get(f"/api/v1/customers?q={raw[:7]}", headers=auth(SALES, NOUR)).json()
    assert created.json()["id"] in [c["id"] for c in found["items"]]


def test_another_showroom_cannot_see_the_car(client: TestClient, sold_car: dict[str, str]) -> None:
    response = client.get(f"/api/v1/vehicles/{sold_car['vehicle']}", headers=auth("owner@doha.example", DOHA))
    assert response.status_code == 404


def test_photo_upload_through_signed_urls(client: TestClient) -> None:
    if isinstance(client.app.state.storage, DisabledStorage):  # type: ignore[attr-defined]
        pytest.skip("storage is not configured (SUPABASE_SERVICE_ROLE_KEY)")
    car = client.post("/api/v1/vehicles", headers=_headers(OWNER), json={"make": "BMW", "model": "320i"}).json()["id"]
    ticket = client.post(
        f"/api/v1/vehicles/{car}/media/upload-url",
        headers=_headers(SALES),
        json={"content_type": "image/png", "size_bytes": 68},
    )
    assert ticket.status_code == 200, ticket.text
    png = bytes.fromhex(
        "89504e470d0a1a0a0000000d4948445200000001000000010806000000"
        "1f15c4890000000d49444154789c6360000002000154a24f5d0000000049454e44ae426082"
    )
    put = httpx.put(ticket.json()["upload_url"], content=png, headers={"Content-Type": "image/png"}, timeout=10)
    assert put.status_code in (200, 201), put.text
    registered = client.post(
        f"/api/v1/vehicles/{car}/media",
        headers=_headers(SALES),
        json={"storage_path": ticket.json()["storage_path"], "content_type": "image/png", "size_bytes": len(png)},
    )
    assert registered.status_code == 201, registered.text
    detail = client.get(f"/api/v1/vehicles/{car}", headers=auth(SALES, NOUR)).json()
    assert detail["media"][0]["url"].startswith("http")
    # A path from another vehicle is refused.
    other = client.post(
        f"/api/v1/vehicles/{car}/media",
        headers=_headers(SALES),
        json={"storage_path": f"{NOUR}/{uuid.uuid4()}/x.png", "content_type": "image/png", "size_bytes": 10},
    )
    assert other.status_code == 422
