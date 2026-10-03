"""Phase 6 acceptance: consignment in (rules 10, 16, 17, P-05, P-06) and out
(rules 18, 19) against the ledger, statements that reconcile with it, request
matching when a car becomes AVAILABLE, and follow-ups (BACKLOG Phase 6)."""

import uuid
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Connection, text
from sqlalchemy.exc import DBAPIError

from app.api.deps import TenantContext
from app.api.routers.sales import _check_cancel_permission
from app.core.errors import AppError
from app.core.security import AuthenticatedUser
from app.domain.consignment import (
    ConsignmentIn,
    ConsignmentReturnIn,
    ConsignorSettlementIn,
    ConsignOutIn,
    ConsignOutReturnIn,
    CustomerRequestIn,
    ExternalCollectionIn,
    ExternalSaleIn,
    ExternalShowroomIn,
    FollowUpIn,
)
from app.domain.sales import SaleCancelIn, SaleDraftIn
from app.domain.vehicles import PurchaseIn, VehicleExpenseIn, VehicleIn
from app.services import consignment, crm, finance, sales, vehicles
from tests.integration.conftest import NOUR, auth
from tests.integration.test_vehicles_sales import (
    NOUR_BANK,
    NOUR_CASH,
    OWNER_ID,
    _category,
    _customer,
    _owner_tx,
    _Rollback,
    _vehicle,
)


def _ledger(conn: Connection, key: str, **ids: uuid.UUID) -> Decimal:
    filters = "".join(f" and l.{column} = :{column}" for column in ids)
    return Decimal(
        conn.execute(
            text(
                "select coalesce(sum(l.debit - l.credit), 0) from public.journal_lines l "  # noqa: S608 - fixed columns
                "join public.ledger_accounts a on a.id = l.ledger_account_id where a.system_key = :key" + filters
            ),
            {"key": key, **ids},
        ).scalar_one()
    )


def _balances(conn: Connection) -> tuple[Decimal, Decimal]:
    return finance.get_cash_account(conn, NOUR_CASH).balance, finance.get_cash_account(conn, NOUR_BANK).balance


def _consign_in(conn: Connection, owner: uuid.UUID, **terms: Any) -> Any:
    today = finance.tenant_info(conn).today
    payload = {
        "consignor_id": owner,
        "vehicle": {"make": "Kia", "model": "Cerato", "year": 2021, "asking_price": "310000"},
        "agreement_date": today,
        "terms_type": "COMMISSION_PCT",
        "commission_value": "5",
    }
    payload.update(terms)
    created = consignment.create_consignment(conn, ConsignmentIn.model_validate(payload), with_money=True)
    vehicles.change_status(conn, created.vehicle_id, "AVAILABLE", None)
    return created


def _expense(conn: Connection, vehicle_id: uuid.UUID, amount: str) -> Any:
    return vehicles.record_expense(
        conn,
        vehicle_id,
        VehicleExpenseIn.model_validate(
            {
                "expense_date": finance.tenant_info(conn).today,
                "category_id": _category(conn, "cleaning"),
                "amount": amount,
                "cash_account_id": NOUR_CASH,
            }
        ),
    )


def _sell(conn: Connection, vehicle_id: uuid.UUID, price: str, **extra: Any) -> Any:
    payload = {
        "vehicle_id": vehicle_id,
        "buyer_customer_id": _customer(conn, "مشتري أمانة"),
        "sale_date": finance.tenant_info(conn).today,
        "list_price": price,
        "payments": [{"cash_account_id": NOUR_BANK, "amount": price}],
    }
    payload.update(extra)
    draft = sales.create_draft(
        conn, SaleDraftIn.model_validate(payload), viewer_id=OWNER_ID, see_all_drafts=True, with_profit=True
    )
    return draft, lambda: sales.post_sale(conn, draft.id, user_id=OWNER_ID, with_profit=True)


def _settle(conn: Connection, consignment_id: uuid.UUID, kind: str, amount: str) -> Any:
    return consignment.record_settlement(
        conn,
        consignment_id,
        ConsignorSettlementIn.model_validate(
            {
                "kind": kind,
                "settle_date": finance.tenant_info(conn).today,
                "amount": amount,
                "cash_account_id": NOUR_BANK if kind == "PAYOUT" else NOUR_CASH,
            }
        ),
    )


# --- Consignment IN ------------------------------------------------------------------------------------


def test_consignment_in_cycle_matches_hand_calculation(client: TestClient) -> None:
    """ACCOUNTING §3, V3 (owner Samir, commission 5%):
    rule 10  cleaning 2,000 in cash -> recoverable from Samir 2,000
    rule 16  sold for 300,000 by bank -> A: owed to Samir 300,000; B: commission 15,000, 2,000 recovered
             -> 283,000 due to Samir; showroom profit 15,000
    rule 17  Samir paid 283,000 by bank -> nothing owed either way
    Cash -2,000; bank +300,000 -283,000 = +17,000."""

    def scenario() -> None:
        with _owner_tx(client) as conn:
            cash_before, bank_before = _balances(conn)
            samir = _customer(conn, "سمير")
            agreement = _consign_in(conn, samir)
            car = agreement.vehicle_id
            detail = vehicles.vehicle_ref(conn, car)
            assert (detail.ownership_type, detail.status) == ("CONSIGNED_IN", "AVAILABLE")

            expense = _expense(conn, car, "2000").document
            assert expense.treatment == "RECOVERABLE"
            assert _ledger(conn, "CONSIGNOR_RECOVERABLE", consignor_id=samir, vehicle_id=car) == Decimal("2000.00")
            assert _ledger(conn, "VEHICLE_INVENTORY", vehicle_id=car) == 0

            _, post = _sell(conn, car, "300000")
            sale = post().document
            assert sale.ownership_type == "CONSIGNED_IN"
            assert sale.profit is not None
            assert (sale.profit.kind, sale.profit.commission, sale.profit.recovered_expenses) == (
                "CONSIGNMENT",
                Decimal("15000.00"),
                Decimal("2000.00"),
            )
            assert sale.profit.due_to_owner == Decimal("283000.00")
            assert sale.profit.gross_profit == Decimal("15000.00")
            assert _ledger(conn, "VEHICLE_SALES", vehicle_id=car) == 0
            assert _ledger(conn, "CONSIGNMENT_COMMISSION", vehicle_id=car) == Decimal("-15000.00")
            assert _ledger(conn, "CONSIGNOR_RECOVERABLE", consignor_id=samir) == 0

            current = consignment.get_consignment(conn, agreement.id, with_money=True)
            assert (current.status, current.payable, current.recoverable) == (
                "SOLD",
                Decimal("283000.00"),
                Decimal("0.00"),
            )
            statement = consignment.consignor_statement(conn, samir)
            assert statement.net_due_to_owner == Decimal("283000.00")
            # The statement reconciles with the ledger: its running balance ends at the net due.
            assert statement.lines[-1].balance == statement.net_due_to_owner

            with pytest.raises(AppError) as over:
                _settle(conn, agreement.id, "PAYOUT", "283000.01")
            assert over.value.code == "CONSIGNOR_OVERPAYMENT"
            _settle(conn, agreement.id, "PAYOUT", "283000")
            assert consignment.get_consignment(conn, agreement.id, with_money=True).payable == 0
            assert consignment.consignor_statement(conn, samir).lines[-1].balance == 0

            cash_after, bank_after = _balances(conn)
            assert cash_after - cash_before == Decimal("-2000.00")
            assert bank_after - bank_before == Decimal("17000.00")

            # D-94: once the owner is paid, the sale is not cancelled.
            with pytest.raises(AppError) as paid:
                sales.cancel_sale(
                    conn, sale.id, SaleCancelIn(reason="تجربة الإلغاء"), user_id=OWNER_ID, with_profit=True
                )
            assert paid.value.code == "CONSIGNOR_ALREADY_PAID"
            raise _Rollback

    with pytest.raises(_Rollback):
        scenario()


def test_net_price_terms_block_a_sale_below_the_net_and_installments(client: TestClient) -> None:
    def scenario() -> None:
        with _owner_tx(client) as conn:
            owner = _customer(conn, "مالك")
            agreement = _consign_in(
                conn, owner, terms_type="NET_PRICE", net_price_to_owner="280000", commission_value=None
            )
            _, post = _sell(conn, agreement.vehicle_id, "280000")
            with pytest.raises(AppError) as below:
                post()
            assert below.value.code == "SALE_BELOW_NET_PRICE"

            today = finance.tenant_info(conn).today
            _, post_financed = _sell(
                conn,
                agreement.vehicle_id,
                "300000",
                payments=[{"cash_account_id": NOUR_BANK, "amount": "100000"}],
                installments={"frequency": "MONTHLY", "count": 2, "first_due_date": today},
            )
            with pytest.raises(AppError) as financed:
                post_financed()
            assert financed.value.code == "CONSIGNMENT_NO_INSTALLMENTS"

            _, post_ok = _sell(conn, agreement.vehicle_id, "300000")
            sale = post_ok().document
            assert sale.profit is not None
            assert sale.profit.commission == Decimal("20000.00")
            assert sale.profit.due_to_owner == Decimal("280000.00")
            raise _Rollback

    with pytest.raises(_Rollback):
        scenario()


def test_shared_expenses_return_and_recovery(client: TestClient) -> None:
    """P-05 shared 40% owner: 1,000 -> 400 recoverable, 600 showroom expense (6280).
    The owner takes the car back and repays the 400 (P-06)."""

    def scenario() -> None:
        with _owner_tx(client) as conn:
            owner = _customer(conn, "مالك")
            agreement = _consign_in(conn, owner, expenses_borne_by="SHARED", shared_owner_pct="40")
            car = agreement.vehicle_id
            assert _expense(conn, car, "1000").document.treatment == "SHARED"
            assert _ledger(conn, "CONSIGNOR_RECOVERABLE", vehicle_id=car) == Decimal("400.00")
            assert _ledger(conn, "EXP_CONSIGNMENT", vehicle_id=car) == Decimal("600.00")

            returned = consignment.return_to_owner(
                conn,
                agreement.id,
                ConsignmentReturnIn(return_date=agreement.agreement_date, reason="طلب صاحبها"),
                with_money=True,
            )
            assert (returned.status, returned.vehicle_status, returned.recoverable) == (
                "RETURNED",
                "RETURNED_TO_OWNER",
                Decimal("400.00"),
            )
            with pytest.raises(AppError) as closed:
                _expense(conn, car, "50")
            assert closed.value.code == "CONSIGNMENT_CLOSED"
            with pytest.raises(AppError) as too_much:
                _settle(conn, agreement.id, "RECOVERY", "400.01")
            assert too_much.value.code == "RECOVERY_EXCEEDS_EXPENSES"
            _settle(conn, agreement.id, "RECOVERY", "400")
            assert _ledger(conn, "CONSIGNOR_RECOVERABLE", vehicle_id=car) == 0
            with pytest.raises(AppError) as not_sold:
                _settle(conn, agreement.id, "PAYOUT", "1")
            assert not_sold.value.code == "CONSIGNMENT_NOT_SOLD"
            raise _Rollback

    with pytest.raises(_Rollback):
        scenario()


def test_cancelling_a_consigned_sale_mirrors_both_entries(client: TestClient) -> None:
    def scenario() -> None:
        with _owner_tx(client) as conn:
            owner = _customer(conn, "مالك")
            agreement = _consign_in(conn, owner, expenses_borne_by="SHOWROOM")
            _expense(conn, agreement.vehicle_id, "500")
            _, post = _sell(conn, agreement.vehicle_id, "200000")
            sale = post().document
            cancelled = sales.cancel_sale(
                conn, sale.id, SaleCancelIn(reason="المشتري تراجع"), user_id=OWNER_ID, with_profit=True
            ).document
            assert cancelled.cancellation_method == "MIRROR"
            assert _ledger(conn, "CONSIGNOR_PAYABLE", vehicle_id=agreement.vehicle_id) == 0
            assert _ledger(conn, "CONSIGNMENT_COMMISSION", vehicle_id=agreement.vehicle_id) == 0
            current = consignment.get_consignment(conn, agreement.id, with_money=True)
            assert (current.status, current.vehicle_status) == ("ACTIVE", "AVAILABLE")
            raise _Rollback

    with pytest.raises(_Rollback):
        scenario()


@pytest.mark.parametrize(
    ("role", "permissions", "allowed"),
    [
        ("ACCOUNTANT", {"sale.cancel"}, False),
        ("MANAGER", {"sale.cancel_consigned"}, True),
        ("OWNER", {"sale.cancel", "sale.cancel_consigned"}, True),
    ],
)
def test_only_owner_and_manager_cancel_a_consigned_sale(
    client: TestClient, role: str, permissions: set[str], allowed: bool
) -> None:
    """Pilot review (Q-41): an accountant cancels ordinary sales but not a consigned car's."""

    def ctx() -> TenantContext:
        return TenantContext(
            user=AuthenticatedUser(id=OWNER_ID, email=None, claims={}),
            tenant_id=uuid.UUID(NOUR),
            membership_id=uuid.uuid4(),
            role_code=role,
            partner_id=None,
            permissions=frozenset(permissions),
            subscription_status="ACTIVE",
        )

    def scenario() -> None:
        with _owner_tx(client) as conn:
            agreement = _consign_in(conn, _customer(conn, "مالك"))
            _, post = _sell(conn, agreement.vehicle_id, "700000")
            sale = post().document
            if allowed:
                _check_cancel_permission(conn, ctx(), sale.id)
            else:
                with pytest.raises(AppError) as refused:
                    _check_cancel_permission(conn, ctx(), sale.id)
                assert refused.value.code == "PERMISSION_DENIED"
            raise _Rollback

    with pytest.raises(_Rollback):
        scenario()


# --- Consignment OUT ------------------------------------------------------------------------------------


def _owned_car(conn: Connection, cost: str) -> uuid.UUID:
    car = _vehicle(conn, "Hyundai", "Tucson", 2020)
    vehicles.record_purchase(
        conn,
        car,
        PurchaseIn.model_validate(
            {
                "seller_customer_id": _customer(conn, "بائع"),
                "purchase_date": finance.tenant_info(conn).today,
                "price": cost,
                "payments": [{"cash_account_id": NOUR_BANK, "amount": cost}],
                "ready_for_sale": True,
            }
        ),
    )
    return car


def test_consignment_out_cycle_matches_hand_calculation(client: TestClient) -> None:
    """ACCOUNTING §3, V4 (cost 350,000) at Al-Amal Motors, commission 8,000, sold for 400,000:
    rule 18 -> receivable 392,000, profit after commission 42,000 (Q-34); rule 19 collects 392,000."""

    def scenario() -> None:
        with _owner_tx(client) as conn:
            today = finance.tenant_info(conn).today
            showroom = consignment.create_showroom(conn, ExternalShowroomIn(name=f"معرض الأمل {uuid.uuid4().hex[:6]}"))
            car = _owned_car(conn, "350000")
            out = consignment.consign_out(
                conn,
                ConsignOutIn.model_validate(
                    {
                        "vehicle_id": car,
                        "external_showroom_id": showroom.id,
                        "sent_date": today,
                        "commission_type": "FIXED",
                        "commission_value": "8000",
                    }
                ),
            )
            assert out.vehicle_status == "AT_OTHER_SHOWROOM"
            location = conn.execute(
                text(
                    "select l.external_showroom_id from public.vehicles v join public.locations l "
                    "on l.id = v.current_location_id where v.id = :id"
                ),
                {"id": car},
            ).scalar_one()
            assert location == showroom.id
            assert [o.id for o in consignment.list_out(conn, status="OUT", showroom_id=showroom.id)] == [out.id]

            posted = consignment.record_external_sale(
                conn,
                out.id,
                ExternalSaleIn.model_validate({"sale_date": today, "sale_price": "400000"}),
                user_id=OWNER_ID,
            )
            assert len(posted.journal_entries) == 3
            assert posted.document.status == "SOLD"
            assert vehicles.vehicle_ref(conn, car).status == "DELIVERED"
            assert consignment.showroom_receivable(conn, showroom.id) == Decimal("392000.00")
            sale = sales.get_sale(
                conn,
                posted.document.sale_id,
                viewer_id=OWNER_ID,
                see_all_drafts=True,
                with_profit=True,  # type: ignore[arg-type]
            )
            assert (sale.channel, sale.buyer_customer_id, sale.invoice_no) == ("EXTERNAL_SHOWROOM", None, None)
            assert sale.profit is not None
            assert (sale.profit.external_commission, sale.profit.gross_profit) == (
                Decimal("8000.00"),
                Decimal("42000.00"),
            )

            _, bank_before = _balances(conn)
            payload = {"collect_date": today, "amount": "392000.01", "cash_account_id": NOUR_BANK}
            with pytest.raises(AppError) as over:
                consignment.record_collection(conn, showroom.id, ExternalCollectionIn.model_validate(payload))
            assert over.value.code == "EXTERNAL_OVERPAYMENT"
            consignment.record_collection(
                conn, showroom.id, ExternalCollectionIn.model_validate({**payload, "amount": "392000"})
            )
            assert _balances(conn)[1] - bank_before == Decimal("392000.00")
            statement = consignment.showroom_statement(conn, showroom.id)
            assert statement.receivable == 0
            assert [line.balance for line in statement.lines] == [
                Decimal("400000.00"),
                Decimal("392000.00"),
                Decimal("0.00"),
            ]

            with pytest.raises(AppError) as final:
                sales.cancel_sale(
                    conn, sale.id, SaleCancelIn(reason="تجربة الإلغاء"), user_id=OWNER_ID, with_profit=True
                )
            assert final.value.code == "SALE_DELIVERED"
            raise _Rollback

    with pytest.raises(_Rollback):
        scenario()


def test_consign_out_and_back_and_no_re_consignment(client: TestClient) -> None:
    def scenario() -> None:
        with _owner_tx(client) as conn:
            today = finance.tenant_info(conn).today
            showroom = consignment.create_showroom(conn, ExternalShowroomIn(name=f"معرض {uuid.uuid4().hex[:6]}"))
            car = _owned_car(conn, "100000")
            payload = {
                "vehicle_id": car,
                "external_showroom_id": showroom.id,
                "sent_date": today,
                "commission_type": "PCT",
                "commission_value": "2",
            }
            out = consignment.consign_out(conn, ConsignOutIn.model_validate(payload))
            back = consignment.return_out(conn, out.id, ConsignOutReturnIn(return_date=today))
            assert (back.status, back.vehicle_status) == ("RETURNED", "AVAILABLE")

            consigned = _consign_in(conn, _customer(conn, "مالك"))
            with pytest.raises(AppError) as q33:
                consignment.consign_out(
                    conn, ConsignOutIn.model_validate({**payload, "vehicle_id": consigned.vehicle_id})
                )
            assert q33.value.code == "VEHICLE_NOT_OWNED"
            raise _Rollback

    with pytest.raises(_Rollback):
        scenario()


# --- Requests and matching ---------------------------------------------------------------------------


def test_a_car_becoming_available_matches_open_requests(client: TestClient) -> None:
    def scenario() -> None:
        with _owner_tx(client) as conn:
            make = f"Make{uuid.uuid4().hex[:6]}"
            wanted = crm.create_request(
                conn,
                CustomerRequestIn.model_validate(
                    {
                        "customer_id": _customer(conn, "عميل يبحث"),
                        "make": make,
                        "model": "Corolla",
                        "year_from": 2018,
                        "year_to": 2021,
                        "budget_max": "450000",
                    }
                ),
            )
            other = crm.create_request(
                conn,
                CustomerRequestIn.model_validate(
                    {"customer_id": _customer(conn, "عميل آخر"), "make": make, "budget_max": "100000"}
                ),
            )
            assert wanted.match_count == 0

            fits = vehicles.create_vehicle(
                conn, VehicleIn(make=make.lower(), model="Corolla XLi", year=2020, asking_price=Decimal(400000))
            )
            too_old = vehicles.create_vehicle(
                conn, VehicleIn(make=make, model="Corolla", year=2015, asking_price=Decimal(300000))
            )
            for car in (fits, too_old):
                vehicles.change_status(conn, car, "IN_PREPARATION", None)
                assert crm.vehicle_matches(conn, car) == []
                vehicles.change_status(conn, car, "AVAILABLE", None)

            matches = crm.vehicle_matches(conn, fits)
            assert [m.request_id for m in matches] == [wanted.id]
            assert matches[0].customer_phone is not None
            assert crm.vehicle_matches(conn, too_old) == []
            assert crm.get_request(conn, other.id).match_count == 0
            alert = conn.execute(
                text(
                    "select params from public.notifications where kind = 'REQUEST_MATCH' and entity_id = :car "
                    "and user_id = :owner"
                ),
                {"car": fits, "owner": OWNER_ID},
            ).scalar_one()
            assert alert["count"] == 1

            contacted = crm.set_contacted(conn, matches[0].id, contacted=True, user_id=OWNER_ID)
            assert contacted.contacted
            assert crm.get_request(conn, wanted.id).status == "VEHICLE_FOUND"

            # A new request is matched against cars already available.
            later = crm.create_request(
                conn,
                CustomerRequestIn.model_validate(
                    {"customer_id": _customer(conn, "عميل ثالث"), "make": make, "model": "corolla"}
                ),
            )
            assert {m.vehicle_id for m in crm.get_request(conn, later.id).matches} == {fits, too_old}
            raise _Rollback

    with pytest.raises(_Rollback):
        scenario()


def test_follow_ups_are_logged_and_due(client: TestClient) -> None:
    def scenario() -> None:
        with _owner_tx(client) as conn:
            today = finance.tenant_info(conn).today
            customer = _customer(conn, "عميل متابعة")
            first = crm.log_follow_up(
                conn,
                FollowUpIn.model_validate(
                    {"customer_id": customer, "result": "CALL_BACK", "next_follow_up_date": today, "priority": "HIGH"}
                ),
                user_id=OWNER_ID,
            )
            assert first.assigned_to == OWNER_ID
            due = crm.due_follow_ups(conn, assigned_to=OWNER_ID)
            assert first.id in {d.follow_up.id for d in due}

            crm.log_follow_up(
                conn, FollowUpIn.model_validate({"customer_id": customer, "result": "NOT_INTERESTED"}), user_id=OWNER_ID
            )
            assert first.id not in {d.follow_up.id for d in crm.due_follow_ups(conn, assigned_to=None)}
            assert len(crm.list_follow_ups(conn, customer_id=customer, limit=10)) == 2
            raise _Rollback

    with pytest.raises(_Rollback):
        scenario()


def test_follow_ups_cannot_be_changed(client: TestClient) -> None:
    with _owner_tx(client) as conn:
        follow_up = crm.log_follow_up(
            conn, FollowUpIn.model_validate({"customer_id": _customer(conn, "عميل")}), user_id=OWNER_ID
        )
        change = text("update public.follow_ups set notes = 'x' where id = :id")
        with pytest.raises(DBAPIError, match="cannot be changed"):
            conn.execute(change, {"id": follow_up.id})


# --- Through the API ----------------------------------------------------------------------------------------


def test_permissions_on_consignment_money_and_follow_ups(client: TestClient) -> None:
    sales_user, viewer = auth("sales@nour.example", NOUR), auth("partner@nour.example", NOUR)
    owner = auth("owner@nour.example", NOUR)
    customer = client.post("/api/v1/customers", headers=owner, json={"name": "عميل API"}).json()["id"]

    assert client.get("/api/v1/consignments", headers=sales_user).status_code == 200
    assert client.get(f"/api/v1/customers/{customer}/consignor-statement", headers=sales_user).status_code == 403
    assert client.get("/api/v1/consignments-out", headers=sales_user).status_code == 200
    assert client.get("/api/v1/consignments", headers=viewer).status_code == 403

    logged = client.post("/api/v1/follow-ups", headers=sales_user, json={"customer_id": customer, "result": "ANSWERED"})
    assert logged.status_code == 201
    assert client.post("/api/v1/follow-ups", headers=viewer, json={"customer_id": customer}).status_code == 403

    statement = client.get(f"/api/v1/customers/{customer}/consignor-statement", headers=owner)
    assert statement.status_code == 200
    assert statement.json()["net_due_to_owner"] == "0.00"
