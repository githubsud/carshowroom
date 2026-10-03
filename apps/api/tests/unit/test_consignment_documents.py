import uuid
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

from app.domain.consignment import ConsignmentOut, ConsignorStatement, StatementLine
from app.reports import consignment_documents

CONSIGNMENT = ConsignmentOut(
    id=uuid.uuid4(),
    vehicle_id=uuid.uuid4(),
    stock_no="V-2026-0006",
    vehicle_label="Mitsubishi Lancer 2017",
    vehicle_status="AVAILABLE",
    consignor_id=uuid.uuid4(),
    consignor_name="سمير عادل",
    consignor_phone="+201006667788",
    agreement_date=date(2026, 9, 20),
    end_date=date(2026, 12, 20),
    expired=False,
    terms_type="COMMISSION_PCT",
    net_price_to_owner=None,
    commission_value=Decimal("5.00"),
    expenses_borne_by="SHARED",
    shared_owner_pct=Decimal("40.00"),
    asking_price=Decimal("310000.00"),
    status="ACTIVE",
    returned_date=None,
    days_with_us=13,
    notes=None,
)

CONTEXT = {
    "consignment": CONSIGNMENT,
    "tenant": {
        "name_ar": "معرض النور",
        "name_en": "Al Nour",
        "address": "القاهرة",
        "commercial_reg_no": "12345",
        "currency_code": "EGP",
    },
    "vehicle": {
        "stock_no": "V-2026-0006",
        "make": "Mitsubishi",
        "model": "Lancer",
        "trim": None,
        "year": 2017,
        "vin": None,
        "plate_no": "ر ي ح 2468",
        "color_ext": "أزرق",
        "mileage_km": 110000,
        "asking_price": Decimal("310000.00"),
    },
    "owner": SimpleNamespace(name="سمير عادل", phone_primary="+201006667788"),
}


def test_agreement_records_parties_car_and_terms_without_legal_clauses() -> None:
    html = consignment_documents.agreement_html(CONTEXT, "ar")
    assert 'dir="rtl"' in html
    assert "اتفاق عرض سيارة بالأمانة" in html
    assert "سمير عادل" in html
    assert "عمولة نسبة من سعر البيع" in html
    assert "5.00%" in html
    assert "40.00%" in html
    assert "توقيع صاحب السيارة" in html
    english = consignment_documents.agreement_html(CONTEXT, "en")
    assert 'dir="ltr"' in english
    assert "Shared; the owner's share" in english


def test_consignor_statement_shows_running_balance_and_net() -> None:
    statement = ConsignorStatement(
        consignor_id=CONSIGNMENT.consignor_id,
        consignor_name="سمير عادل",
        consignor_phone=None,
        as_of=date(2026, 10, 7),
        currency_code="EGP",
        lines=[
            StatementLine(
                entry_date=date(2026, 10, 7),
                entry_no=40,
                description="بيع",
                stock_no="V-2026-0006",
                debit=Decimal("0"),
                credit=Decimal("300000.00"),
                balance=Decimal("300000.00"),
            )
        ],
        payable=Decimal("300000.00"),
        recoverable=Decimal("0"),
        net_due_to_owner=Decimal("300000.00"),
        consignments=[],
    )
    html = consignment_documents.consignor_statement_html(statement, "ar", "معرض النور")
    assert "كشف حساب صاحب سيارة أمانة" in html
    assert "V-2026-0006" in html
    assert "300,000.00" in html
