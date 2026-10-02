"""Phase 5 acceptance: the scenario with installments passes and the overdue
lists are correct (SPEC §13); a bounced cheque restores the receivable and the
bank balance (SPEC §7 test list)."""

import uuid
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Connection, text

from app.core.errors import AppError
from app.domain.installments import PaperActionIn, PaperIn, ReceiptIn
from app.domain.sales import SaleCancelIn, SaleDraftIn
from app.domain.vehicles import PurchaseIn, VehicleExpenseIn
from app.integrations.messaging import LogSmsProvider
from app.services import customers, finance, installments, notifications, papers, sales, vehicles
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


def _receivable(conn: Connection, customer_id: uuid.UUID) -> Decimal:
    return Decimal(
        conn.execute(
            text(
                """
                select coalesce(sum(l.debit - l.credit), 0)
                  from public.journal_lines l join public.ledger_accounts a on a.id = l.ledger_account_id
                 where l.customer_id = :id and a.system_key = 'INSTALLMENT_RECEIVABLE'
                """
            ),
            {"id": customer_id},
        ).scalar_one()
    )


def _bank(conn: Connection) -> Decimal:
    return finance.get_cash_account(conn, NOUR_BANK).balance


def _cash(conn: Connection) -> Decimal:
    return finance.get_cash_account(conn, NOUR_CASH).balance


def _installment_sale(
    conn: Connection,
    *,
    cost: str,
    price: str,
    down: str,
    count: int,
    first_due: date,
    sale_date: date | None = None,
    buyer: uuid.UUID | None = None,
) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    """Buy a car by bank for `cost`, sell it with `down` in cash and the rest in
    `count` monthly installments. Returns (customer, sale, plan)."""
    today = finance.tenant_info(conn).today
    seller = _customer(conn, "بائع")
    buyer = buyer or _customer(conn, "مريم")
    car = _vehicle(conn, "Toyota", "Corolla", 2020)
    day = sale_date or today
    vehicles.record_purchase(
        conn,
        car,
        PurchaseIn.model_validate(
            {
                "seller_customer_id": seller,
                "purchase_date": day,
                "price": cost,
                "payments": [{"cash_account_id": NOUR_BANK, "amount": cost}],
                "ready_for_sale": True,
            }
        ),
    )
    draft = sales.create_draft(
        conn,
        SaleDraftIn.model_validate(
            {
                "vehicle_id": car,
                "buyer_customer_id": buyer,
                "sale_date": day,
                "list_price": price,
                "payments": [{"cash_account_id": NOUR_CASH, "amount": down}],
                "installments": {"frequency": "MONTHLY", "count": count, "first_due_date": first_due},
            }
        ),
        viewer_id=OWNER_ID,
        see_all_drafts=True,
        with_profit=True,
    )
    sale = sales.post_sale(conn, draft.id, user_id=OWNER_ID, with_profit=True).document
    assert sale.plan_id is not None
    return buyer, sale.id, sale.plan_id


def _receive(conn: Connection, plan_id: uuid.UUID, amount: str, **extra: Any) -> Any:
    payload = {"receipt_date": finance.tenant_info(conn).today, "amount": amount, "cash_account_id": NOUR_CASH}
    payload.update(extra)
    return installments.record_receipt(conn, plan_id, ReceiptIn.model_validate(payload))


# --- The scenario -----------------------------------------------------------------------------------


def test_installment_sale_and_collections_match_hand_calculation(client: TestClient) -> None:
    """ACCOUNTING §4, Car2: cost 500,000 + 20,000 cash expense = 520,000; sold for
    640,000 with 160,000 cash down and 6 monthly installments of 80,000 (rule 13);
    two installments collected in cash (rule 15) -> receivable 320,000; profit 120,000.
    A partial payment of 30,000 leaves 50,000 on installment 3."""

    def scenario() -> None:
        with _owner_tx(client) as conn:
            cash_before, bank_before = _cash(conn), _bank(conn)
            today = finance.tenant_info(conn).today
            seller, buyer = _customer(conn, "بائع"), _customer(conn, "مريم")
            car = _vehicle(conn, "Toyota", "Corolla", 2020)
            vehicles.record_purchase(
                conn,
                car,
                PurchaseIn.model_validate(
                    {
                        "seller_customer_id": seller,
                        "purchase_date": today,
                        "price": "500000",
                        "payments": [{"cash_account_id": NOUR_BANK, "amount": "500000"}],
                        "ready_for_sale": True,
                    }
                ),
            )
            vehicles.record_expense(
                conn,
                car,
                VehicleExpenseIn.model_validate(
                    {
                        "expense_date": today,
                        "category_id": _category(conn, "maintenance"),
                        "amount": "20000",
                        "cash_account_id": NOUR_CASH,
                    }
                ),
            )
            draft = sales.create_draft(
                conn,
                SaleDraftIn.model_validate(
                    {
                        "vehicle_id": car,
                        "buyer_customer_id": buyer,
                        "sale_date": today,
                        "list_price": "640000",
                        "payments": [{"cash_account_id": NOUR_CASH, "amount": "160000"}],
                        "installments": {
                            "frequency": "MONTHLY",
                            "count": 6,
                            "first_due_date": today + timedelta(days=30),
                        },
                    }
                ),
                viewer_id=OWNER_ID,
                see_all_drafts=True,
                with_profit=True,
            )
            assert (draft.financed, draft.remaining) == (Decimal("480000.00"), Decimal("0.00"))
            sale = sales.post_sale(conn, draft.id, user_id=OWNER_ID, with_profit=True).document
            assert sale.profit is not None
            assert sale.profit.gross_profit == Decimal("120000.00")
            assert sale.plan_id is not None
            plan = installments.get_plan(conn, sale.plan_id, with_papers=True)
            assert [i.amount_due for i in plan.installments] == [Decimal("80000.00")] * 6
            assert _receivable(conn, buyer) == Decimal("480000.00")

            _receive(conn, sale.plan_id, "160000")
            plan = installments.get_plan(conn, sale.plan_id, with_papers=True)
            assert [i.state for i in plan.installments[:3]] == ["PAID", "PAID", "UPCOMING"]
            assert _receivable(conn, buyer) == Decimal("320000.00")
            assert plan.remaining_total == Decimal("320000.00")

            _receive(conn, sale.plan_id, "30000")
            plan = installments.get_plan(conn, sale.plan_id, with_papers=True)
            assert (plan.installments[2].paid, plan.installments[2].remaining) == (
                Decimal("30000.00"),
                Decimal("50000.00"),
            )
            assert plan.receipts[-1].allocations[0].seq == 3

            # Business rule 3: never more than what is owed (BLOCK, the default).
            with pytest.raises(AppError) as over:
                _receive(conn, sale.plan_id, "290000.01")
            assert over.value.code == "PAYMENT_EXCEEDS_OUTSTANDING"
            assert over.value.details["outstanding"] == "290000.00"

            assert _cash(conn) - cash_before == Decimal("-20000.00") + Decimal("160000.00") + Decimal("190000.00")
            assert _bank(conn) - bank_before == Decimal("-500000.00")
            raise _Rollback

    with pytest.raises(_Rollback):
        scenario()


def test_overpayment_kept_as_credit_when_the_showroom_allows_it(client: TestClient) -> None:
    def scenario() -> None:
        with _owner_tx(client) as conn:
            conn.execute(text("update public.tenant_settings set overpayment_policy = 'ALLOW_AS_CREDIT'"))
            today = finance.tenant_info(conn).today
            buyer, _, plan_id = _installment_sale(
                conn, cost="100000", price="130000", down="30000", count=2, first_due=today + timedelta(days=30)
            )
            with pytest.raises(AppError):
                _receive(conn, plan_id, "105000")  # the user did not tick "keep as credit"
            _receive(conn, plan_id, "105000", keep_excess_as_credit=True)
            assert installments.get_plan(conn, plan_id, with_papers=False).remaining_total == Decimal("0.00")
            assert customers.credit_owed(conn, buyer) == Decimal("5000.00")
            raise _Rollback

    with pytest.raises(_Rollback):
        scenario()


def test_customer_credit_pays_an_installment(client: TestClient) -> None:
    def scenario() -> None:
        with _owner_tx(client) as conn:
            conn.execute(text("update public.tenant_settings set overpayment_policy = 'ALLOW_AS_CREDIT'"))
            today = finance.tenant_info(conn).today
            buyer, _, plan_id = _installment_sale(
                conn, cost="100000", price="130000", down="30000", count=2, first_due=today + timedelta(days=30)
            )
            _receive(conn, plan_id, "110000", keep_excess_as_credit=True)  # 100,000 owed -> 10,000 credit
            _, _, second = _installment_sale(
                conn, cost="50000", price="70000", down="30000", count=1, first_due=today, buyer=buyer
            )
            cash_before = _cash(conn)
            installments.record_receipt(
                conn,
                second,
                ReceiptIn.model_validate({"receipt_date": today, "amount": "10000", "source": "CREDIT"}),
            )
            assert customers.credit_owed(conn, buyer) == Decimal("0.00")
            assert installments.get_plan(conn, second, with_papers=False).remaining_total == Decimal("30000.00")
            assert _cash(conn) == cash_before
            raise _Rollback

    with pytest.raises(_Rollback):
        scenario()


# --- Deferred papers --------------------------------------------------------------------------------------


def test_bounced_cheque_restores_the_receivable_and_the_bank(client: TestClient) -> None:
    """A post-dated cheque for installment 1 is deposited and collected into the
    bank (rule 15 at collection, A-10), then bounces (rule 27) with 150 of bank
    charges recharged to the customer (P-07)."""

    def scenario() -> None:
        with _owner_tx(client) as conn:
            today = finance.tenant_info(conn).today
            buyer, _, plan_id = _installment_sale(
                conn, cost="100000", price="160000", down="0.01", count=2, first_due=today
            )
            plan = installments.get_plan(conn, plan_id, with_papers=False)
            first = plan.installments[0]
            paper = papers.create_paper(
                conn,
                PaperIn.model_validate(
                    {
                        "paper_type": "PDC",
                        "number": f"CHQ-{uuid.uuid4().hex[:8]}",
                        "customer_id": buyer,
                        "installment_id": first.id,
                        "amount": first.amount_due,
                        "due_date": today,
                        "drawer_bank": "QNB",
                    }
                ),
            )
            bank_before, receivable_before = _bank(conn), _receivable(conn, buyer)

            def do(action: str, **extra: Any) -> Any:
                return papers.act(
                    conn, paper.id, PaperActionIn.model_validate({"action": action, "action_date": today, **extra})
                )

            # A cheque cannot bounce before it is presented.
            with pytest.raises(AppError) as early:
                do("BOUNCE")
            assert early.value.code == "PAPER_INVALID_TRANSITION"

            do("DEPOSIT")
            assert _bank(conn) == bank_before  # A-10: no money moves on deposit
            do("COLLECT", cash_account_id=NOUR_BANK)
            assert _bank(conn) - bank_before == first.amount_due
            assert installments.get_plan(conn, plan_id, with_papers=False).installments[0].state == "PAID"

            bounced = do("BOUNCE", bank_charges="150", charge_customer=True)
            assert bounced.document.status == "BOUNCED"
            assert [e.to_status for e in bounced.document.events] == ["HELD", "DEPOSITED", "COLLECTED", "BOUNCED"]
            reopened = installments.get_plan(conn, plan_id, with_papers=True).installments[0]
            assert (reopened.remaining, reopened.state, reopened.customer_bounced) == (
                first.amount_due,
                "DUE_TODAY",
                True,
            )
            assert _receivable(conn, buyer) == receivable_before
            assert _bank(conn) - bank_before == Decimal("-150.00")
            other_receivable = conn.execute(
                text(
                    """
                    select coalesce(sum(l.debit - l.credit), 0) from public.journal_lines l
                      join public.ledger_accounts a on a.id = l.ledger_account_id
                     where l.customer_id = :id and a.system_key = 'OTHER_RECEIVABLE'
                    """
                ),
                {"id": buyer},
            ).scalar_one()
            assert other_receivable == Decimal("150.00")
            alerts = conn.execute(
                text("select count(*) from public.notifications where kind = 'CHEQUE_BOUNCED' and entity_id = :id"),
                {"id": paper.id},
            ).scalar_one()
            assert alerts >= 1
            raise _Rollback

    with pytest.raises(_Rollback):
        scenario()


# --- Overdue lists and reminders -------------------------------------------------------------------------


def test_overdue_lists_and_daily_reminders(client: TestClient) -> None:
    """A sale 40 days ago in 3 monthly installments from that day: installment 1
    is 40 days late, 2 about 10 days late, 3 still to come."""

    def scenario() -> None:
        with _owner_tx(client) as conn:
            today = finance.tenant_info(conn).today
            start = today - timedelta(days=40)
            buyer, _, plan_id = _installment_sale(
                conn, cost="50000", price="90000", down="30000", count=3, first_due=start, sale_date=start
            )
            overdue = list(
                installments.list_installments(
                    conn, view="overdue", days=7, customer_id=buyer, date_from=None, date_to=None
                )
            )
            assert [i.seq for i in overdue] == [1, 2]
            assert overdue[0].days_late == 40
            assert all(i.state == "OVERDUE" for i in overdue)
            board = installments.board(conn, view="overdue", days=7, customer_id=buyer)
            assert board.overdue == Decimal("40000.00")
            assert board.customers[0].overdue == Decimal("40000.00")
            assert board.customers[0].outstanding == Decimal("60000.00")

            _receive(conn, plan_id, "20000")  # pays installment 1 only
            after = installments.list_installments(
                conn, view="overdue", days=7, customer_id=buyer, date_from=None, date_to=None
            )
            assert [i.seq for i in after] == [2]

            first = notifications.run_reminders(conn, today, LogSmsProvider())
            assert first is not None
            assert first["overdue"] >= 1
            created = conn.execute(
                text(
                    "select count(*) from public.notifications n join public.installments i on i.id = n.entity_id "
                    "where i.plan_id = :plan"
                ),
                {"plan": plan_id},
            ).scalar_one()
            assert created >= 1
            # Once a day: the second run the same day does nothing.
            assert notifications.run_reminders(conn, today, LogSmsProvider()) is None
            raise _Rollback

    with pytest.raises(_Rollback):
        scenario()


# --- Cancellation with installments (D-41) -------------------------------------------------------------------


def test_cancelling_an_installment_sale_owes_back_what_was_collected(client: TestClient) -> None:
    def scenario() -> None:
        with _owner_tx(client) as conn:
            today = finance.tenant_info(conn).today
            buyer, sale_id, plan_id = _installment_sale(
                conn, cost="300000", price="400000", down="100000", count=3, first_due=today + timedelta(days=10)
            )
            _receive(conn, plan_id, "100000")
            held = papers.create_paper(
                conn,
                PaperIn.model_validate(
                    {
                        "paper_type": "PROMISSORY_NOTE",
                        "number": f"N-{uuid.uuid4().hex[:6]}",
                        "customer_id": buyer,
                        "installment_id": installments.get_plan(conn, plan_id, with_papers=False).installments[1].id,
                        "amount": "100000",
                        "due_date": today + timedelta(days=40),
                    }
                ),
            )
            # MIRROR cannot undo collected installments (D-41).
            conn.execute(text("update public.tenant_settings set sale_cancellation_method = 'MIRROR'"))
            with pytest.raises(AppError) as blocked:
                sales.cancel_sale(conn, sale_id, SaleCancelIn(reason="تجربة"), user_id=OWNER_ID, with_profit=True)
            assert blocked.value.code == "SALE_HAS_COLLECTIONS"

            conn.execute(text("update public.tenant_settings set sale_cancellation_method = 'REFUND_LIABILITY'"))
            sales.cancel_sale(conn, sale_id, SaleCancelIn(reason="تراجع العميل"), user_id=OWNER_ID, with_profit=True)
            assert customers.credit_owed(conn, buyer) == Decimal("200000.00")  # down 100,000 + collected 100,000
            assert _receivable(conn, buyer) == Decimal("0.00")
            plan = installments.get_plan(conn, plan_id, with_papers=True)
            assert plan.status == "CANCELLED"
            assert all(i.state in ("PAID", "CANCELLED") for i in plan.installments)
            assert papers.get_paper(conn, held.id).status == "RETURNED"
            # Business rule 2: no new payments against a cancelled sale.
            with pytest.raises(AppError) as late:
                _receive(conn, plan_id, "1000")
            assert late.value.code == "SALE_CANCELLED"
            raise _Rollback

    with pytest.raises(_Rollback):
        scenario()


# --- Through the API -------------------------------------------------------------------------------------------


def test_schedule_preview_and_permissions(client: TestClient) -> None:
    preview = client.post(
        "/api/v1/installment-plans/schedule-preview",
        headers=auth("sales@nour.example", NOUR),
        json={"financed": "450000", "plan": {"frequency": "MONTHLY", "count": 7, "first_due_date": "2026-11-01"}},
    )
    assert preview.status_code == 200
    rows = preview.json()
    assert (rows[0]["amount"], rows[-1]["amount"], rows[-1]["due_date"]) == ("64285.71", "64285.74", "2027-05-01")

    # Sales staff see the due list read-only (Q-05) but cannot collect or manage papers.
    assert client.get("/api/v1/installments/board", headers=auth("sales@nour.example", NOUR)).status_code == 200
    assert client.get("/api/v1/deferred-papers", headers=auth("sales@nour.example", NOUR)).status_code == 403
    collect = client.post(
        f"/api/v1/installment-plans/{uuid.uuid4()}/receipts/preview",
        headers=auth("sales@nour.example", NOUR),
        json={"receipt_date": "2026-10-01", "amount": "1", "cash_account_id": str(NOUR_CASH)},
    )
    assert collect.status_code == 403
    kpis = client.get("/api/v1/installments/kpis", headers=auth("owner@nour.example", NOUR))
    assert kpis.status_code == 200
    assert set(kpis.json()) >= {"due_48h", "due_7d", "overdue", "bounced_count"}


def test_notifications_are_personal_and_can_be_marked_read(client: TestClient) -> None:
    headers = auth("accountant@nour.example", NOUR)
    database = client.app.state.database  # type: ignore[attr-defined]
    with database.transaction(user_id=OWNER_ID, tenant_id=uuid.UUID(NOUR)) as conn:
        key = f"test:{uuid.uuid4()}"
        created = notifications.notify_permission(
            conn,
            permission="installment.view",
            kind="INSTALLMENT_DUE_SOON",
            params={"customer": "test"},
            entity_type=None,
            entity_id=None,
            dedupe_key=key,
        )
        again = notifications.notify_permission(
            conn,
            permission="installment.view",
            kind="INSTALLMENT_DUE_SOON",
            params={"customer": "test"},
            entity_type=None,
            entity_id=None,
            dedupe_key=key,
        )
    assert created >= 3  # owner, accountant, sales hold installment.view
    assert again == 0
    page = client.get("/api/v1/notifications?unread_only=true", headers=headers).json()
    assert page["unread"] >= 1
    first = page["items"][0]["id"]
    assert client.post(f"/api/v1/notifications/{first}/read", headers=headers).status_code == 204
    assert client.post("/api/v1/notifications/read-all", headers=headers).status_code == 204
    assert client.get("/api/v1/notifications", headers=headers).json()["unread"] == 0
