"""Excel import parsing (BACKLOG 8.1-8.3): messy numbers and dates as showrooms
really type them, header detection in sheets with titles above the table, and
the suggested mapping for Arabic and English headers."""

import uuid
from datetime import date
from decimal import Decimal

import pytest

from app.domain.imports import (
    ParseError,
    detect_header_row,
    detect_kind,
    normalize_header,
    parse_date,
    parse_number,
    suggest_mapping,
)
from app.domain.ledger import Account, CashAccountRef, Line
from app.services.posting import rules


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("400000", "400000.00"),
        ("400,000", "400000.00"),
        ("400,000.50", "400000.50"),
        ("٤٠٠٬٠٠٠", "400000.00"),
        ("٤٠٠٠٠٠٫٥", "400000.50"),
        ("400.000,75", "400000.75"),
        ("12,5", "12.50"),
        ("EGP 15,000", "15000.00"),
        ("15000 ج.م", "15000.00"),
        ("15,000 جنيه", "15000.00"),
        ("ر.ق 2,500", "2500.00"),
        ("(1,250)", "-1250.00"),
        ("1250-", "-1250.00"),
        (" 7 500 ", "7500.00"),
        ("3500.0", "3500.00"),
    ],
)
def test_numbers_as_people_type_them(raw: str, expected: str) -> None:
    assert parse_number(raw) == Decimal(expected)


@pytest.mark.parametrize("raw", ["abc", "12.3.4", "١٢abc", "1,2,3.4.5", "--5"])
def test_bad_numbers_are_reported(raw: str) -> None:
    with pytest.raises(ParseError) as error:
        parse_number(raw)
    assert error.value.code == "BAD_NUMBER"


def test_more_than_two_decimals_is_refused() -> None:
    with pytest.raises(ParseError):
        parse_number("10.005")


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("2026-09-03", date(2026, 9, 3)),
        ("2026-09-03T00:00:00", date(2026, 9, 3)),
        ("03/09/2026", date(2026, 9, 3)),
        ("3/9/2026", date(2026, 9, 3)),
        ("3-9-26", date(2026, 9, 3)),
        ("03.09.2026", date(2026, 9, 3)),
        ("٠٣/٠٩/٢٠٢٦", date(2026, 9, 3)),
        ("2026/9/3", date(2026, 9, 3)),
        ("46268", date(2026, 9, 3)),  # Excel serial
    ],
)
def test_dates_as_people_type_them(raw: str, expected: date) -> None:
    assert parse_date(raw) == expected


@pytest.mark.parametrize("raw", ["31/02/2026", "next week", "2026-13-01", "99999999"])
def test_bad_dates_are_reported(raw: str) -> None:
    with pytest.raises(ParseError) as error:
        parse_date(raw)
    assert error.value.code == "BAD_DATE"


def test_headers_are_normalised_for_matching() -> None:
    assert normalize_header("  رقم الشاسيه ") == normalize_header("رقم الشاسية")
    assert normalize_header("سعر  الشراء:") == "سعر الشراء"
    assert normalize_header("الإسم") == normalize_header("الاسم")
    assert normalize_header("Purchase Price") == "purchase price"


def test_the_header_row_is_found_below_a_title() -> None:
    rows = [
        ["كشف عربيات المعرض - سبتمبر", None, None],
        [None, None, None],
        ["الماركة", "الموديل", "رقم الشاسيه", "سعر الشراء"],
        ["Toyota", "Corolla", "JTD123", "400000"],
    ]
    assert detect_header_row(rows) == 2


def test_kind_and_mapping_are_suggested() -> None:
    headers = ["الماركة", "الموديل", "سنة الصنع", "رقم الشاسيه", "اللوحة", "سعر الشراء", "نقل", "صيانة", "ملاحظات", "x"]
    assert detect_kind(headers, "Sheet1") == "VEHICLES"
    assert suggest_mapping(headers, "VEHICLES") == [
        "make",
        "model",
        "year",
        "vin",
        "plate_no",
        "purchase_price",
        "expense",
        "expense",
        "notes",
        None,
    ]


def test_sheet_names_help_detect_the_kind() -> None:
    assert detect_kind(["الاسم", "الموبايل"], "العملاء") == "CUSTOMERS"
    assert detect_kind(["الاسم", "النسبة", "رأس المال"], "Sheet2") == "PARTNERS"
    assert detect_kind(["العميل", "تاريخ الاستحقاق", "قيمة القسط"], "أقساط") == "INSTALLMENTS"
    assert detect_kind(["الحساب", "الرصيد"], "الخزنة") == "CASH"


# --- Rule 25 and P-08 -----------------------------------------------------------------------------------

GO_LIVE = date(2026, 10, 1)


def test_rule_25_opening_entry_is_balanced_by_opening_equity() -> None:
    """ACCOUNTING §3 rule 25: cash 200,000, bank 800,000, V5 300,000, Mariam 120,000,
    owed to Karim 50,000, capital 600,000 + 400,000 -> opening equity 370,000."""
    cash = CashAccountRef(cash_account_id=uuid.uuid4(), ledger_account_id=uuid.uuid4())
    bank = CashAccountRef(cash_account_id=uuid.uuid4(), ledger_account_id=uuid.uuid4())
    v5, mariam, karim, ahmed, mona = (uuid.uuid4() for _ in range(5))
    lines = [
        Line(account=cash.account, debit=Decimal("200000.00"), cash_account_id=cash.cash_account_id),
        Line(account=bank.account, debit=Decimal("800000.00"), cash_account_id=bank.cash_account_id),
        Line(account=Account.system("VEHICLE_INVENTORY"), debit=Decimal("300000.00"), vehicle_id=v5),
        Line(account=Account.system("INSTALLMENT_RECEIVABLE"), debit=Decimal("120000.00"), customer_id=mariam),
        Line(account=Account.system("SELLER_PAYABLE"), credit=Decimal("50000.00"), customer_id=karim, vehicle_id=v5),
        Line(account=Account.system("PARTNER_CAPITAL"), credit=Decimal("600000.00"), partner_id=ahmed),
        Line(account=Account.system("PARTNER_CAPITAL"), credit=Decimal("400000.00"), partner_id=mona),
    ]
    draft = rules.opening_balances(entry_date=GO_LIVE, lines=lines, description="أرصدة افتتاحية", source_id=None)
    assert draft.is_opening
    assert draft.source_type == "OPENING_BALANCE"
    assert draft.lines[-1] == Line(account=Account.system("OPENING_BALANCE_EQUITY"), credit=Decimal("370000.00"))
    assert sum(line.debit for line in draft.lines) == Decimal("1420000.00")


def test_p08_opening_equity_is_cleared_to_partners() -> None:
    ahmed, mona = uuid.uuid4(), uuid.uuid4()
    draft = rules.opening_equity_clearing(
        entry_date=GO_LIVE,
        allocations=[(ahmed, "CAPITAL", Decimal("200000.00")), (mona, "CURRENT", Decimal("170000.00"))],
        description="توزيع حقوق الافتتاح",
        source_id=None,
    )
    assert draft.lines == (
        Line(account=Account.system("OPENING_BALANCE_EQUITY"), debit=Decimal("370000.00")),
        Line(account=Account.system("PARTNER_CAPITAL"), credit=Decimal("200000.00"), partner_id=ahmed),
        Line(account=Account.system("PARTNER_CURRENT"), credit=Decimal("170000.00"), partner_id=mona),
    )
