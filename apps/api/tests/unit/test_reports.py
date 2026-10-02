"""Report rendering helpers that need no database."""

from datetime import date
from decimal import Decimal
from uuid import uuid4

from app.domain.finance import CashAccountOut, CashBookMovement, CashBookOut
from app.reports.cash_book import render_html, render_xlsx, sheet_title


def _book() -> CashBookOut:
    account = CashAccountOut(
        id=uuid4(),
        kind="CASH_BOX",
        name_ar="الخزنة الرئيسية",
        name_en="Main cash box",
        ledger_account_code="1101",
        bank_name=None,
        account_number=None,
        iban=None,
        is_default=True,
        archived=False,
        balance=Decimal("175000.00"),
    )
    movement = CashBookMovement(
        entry_date=date(2026, 9, 1),
        entry_no=1,
        description="أرصدة افتتاحية",
        source_type="OPENING_BALANCE",
        counterpart_ar="أرصدة افتتاحية",
        counterpart_en="Opening balance equity",
        amount_in=Decimal("200000.00"),
        amount_out=Decimal("0"),
        balance=Decimal("200000.00"),
        is_reversal=False,
        reversed=False,
    )
    return CashBookOut(
        cash_account=account,
        date_from=date(2026, 9, 1),
        date_to=date(2026, 9, 30),
        currency_code="EGP",
        opening_balance=Decimal("0"),
        total_in=Decimal("200000.00"),
        total_out=Decimal("0"),
        closing_balance=Decimal("200000.00"),
        movements=[movement],
    )


def test_excel_sheet_titles_are_sanitised() -> None:
    assert sheet_title("دفتر الخزنة / البنك") == "دفتر الخزنة - البنك"
    assert sheet_title(r"a[b]c:d*e?f\g") == "a-b-c-d-e-f-g"
    assert len(sheet_title("x" * 40)) == 31


def test_xlsx_renders_in_both_languages() -> None:
    for language in ("ar", "en"):
        content = render_xlsx(_book(), language)  # type: ignore[arg-type]
        assert content[:2] == b"PK"


def test_html_is_rtl_in_arabic_and_escapes_text() -> None:
    book = _book()
    book.movements[0].description = "<script>x</script>"
    html = render_html(book, "ar", "معرض النور")
    assert 'dir="rtl"' in html
    assert "<script>" not in html
    assert "200,000.00 ج.م" in html
    assert 'dir="ltr"' in render_html(book, "en", "Al Nour")


def test_pdf_renders_where_pango_is_installed() -> None:
    """Runs in CI and in the Docker image; skipped on machines without Pango (e.g. plain Windows)."""
    import pytest

    from app.core.errors import AppError
    from app.reports.cash_book import render_pdf

    try:
        pdf = render_pdf(_book(), "ar", "معرض النور")
    except AppError as exc:
        if exc.code != "PDF_UNAVAILABLE":
            raise
        pytest.skip("Pango is not installed here")
    assert pdf.startswith(b"%PDF-")
