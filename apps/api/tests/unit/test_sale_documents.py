from datetime import date
from decimal import Decimal

from app.domain.sales import TradeInIn
from app.reports import sale_documents

CONTEXT = {
    "sale": {
        "sale_no": "S-2026-0001",
        "invoice_no": "INV-2026-00001",
        "sale_date": date(2026, 9, 25),
        "buyer_name": "حسن علي",
        "buyer_phone": "+201002223344",
        "list_price": Decimal("270000.00"),
        "discount": Decimal("10000.00"),
        "sale_price": Decimal("260000.00"),
        "deposit_applied": Decimal("0.00"),
    },
    "tenant": {
        "name_ar": "معرض النور",
        "name_en": "Al Nour",
        "address": "القاهرة",
        "phones": ["+20223456789"],
        "commercial_reg_no": "12345",
        "currency_code": "EGP",
    },
    "vehicle": {
        "stock_no": "V-2026-0004",
        "make": "Nissan",
        "model": "Sunny",
        "trim": None,
        "year": 2018,
        "vin": "3N1CN7AP5JL801234",
        "plate_no": "م ع ل 3456",
        "color_ext": "أحمر",
        "mileage_km": 95000,
    },
    "payments": [
        {"cash_account_name_ar": "الخزنة", "cash_account_name_en": "Cash", "reference": None, "amount": "200000.00"}
    ],
    "trade_in": TradeInIn(make="Kia", model="Rio", year=2012, agreed_value=Decimal("60000")),
}


def test_invoice_shows_price_payments_and_trade_in_without_tax() -> None:
    html = sale_documents.render_html(CONTEXT, "invoice", "ar")
    assert 'dir="rtl"' in html
    assert "فاتورة بيع سيارة" in html
    assert "INV-2026-00001" in html
    assert "3N1CN7AP5JL801234" in html
    assert "260,000.00" in html  # net price after the 10,000 discount (P-12)
    assert "Kia Rio 2012" in html
    assert "ضريبة" not in html  # no tax lines (D-39)


def test_contract_has_signature_lines_in_english() -> None:
    html = sale_documents.render_html(CONTEXT, "contract", "en")
    assert "Vehicle sale contract" in html
    assert "Seller signature" in html
    assert "Buyer signature" in html
    assert sale_documents.filename(CONTEXT, "contract") == "contract-INV-2026-00001.pdf"


def test_an_installment_contract_states_one_fixed_deferred_price() -> None:
    """docs/SHARIA.md: cash price 600,000, 150,000 down, a 60,000 installment price
    difference -> one agreed price of 660,000, the rest in 6 installments, and the
    price never increases with late payment."""
    sale = {
        **CONTEXT["sale"],
        "list_price": Decimal("600000.00"),
        "discount": Decimal("0.00"),
        "sale_price": Decimal("600000.00"),
        "installment_plan": {"frequency": "MONTHLY", "count": 6, "first_due_date": "2026-11-01", "markup": "60000.00"},
        "receivable_amount": Decimal("510000.00"),
    }
    context = {**CONTEXT, "sale": sale, "trade_in": None}
    html = sale_documents.render_html(context, "contract", "ar")
    assert "فرق سعر التقسيط" in html
    assert "الثمن الإجمالي (بيع بالتقسيط)" in html
    assert "660,000.00" in html
    assert "الباقي على 6 قسط، أولها 2026-11-01" in html
    assert "510,000.00" in html
    assert "لا يزيد بأي حال عند التأخر في السداد" in html
    assert "فائدة" not in html
