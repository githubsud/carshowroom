"""Customer installment statement (كشف أقساط العميل, SPEC §4.8): printable PDF."""

from decimal import Decimal
from html import escape
from typing import Literal

from app.domain.installments import CustomerInstallmentStatement
from app.domain.money import format_money
from app.reports.cash_book import FONTS, html_to_pdf

Language = Literal["ar", "en"]

_L: dict[str, dict[Language, str]] = {
    "title": {"ar": "كشف أقساط العميل", "en": "Customer installment statement"},
    "customer": {"ar": "العميل", "en": "Customer"},
    "as_of": {"ar": "حتى تاريخ", "en": "As of"},
    "sale": {"ar": "البيع", "en": "Sale"},
    "seq": {"ar": "القسط", "en": "No."},
    "due": {"ar": "الاستحقاق", "en": "Due date"},
    "amount": {"ar": "القيمة", "en": "Amount"},
    "paid": {"ar": "المدفوع", "en": "Paid"},
    "remaining": {"ar": "المتبقي", "en": "Remaining"},
    "state": {"ar": "الحالة", "en": "Status"},
    "financed": {"ar": "إجمالي التقسيط", "en": "Financed"},
    "overdue": {"ar": "متأخر", "en": "Overdue"},
    "PAID": {"ar": "مدفوع", "en": "Paid"},
    "OVERDUE": {"ar": "متأخر", "en": "Overdue"},
    "DUE_TODAY": {"ar": "مستحق اليوم", "en": "Due today"},
    "UPCOMING": {"ar": "قادم", "en": "Upcoming"},
    "CANCELLED": {"ar": "ملغي", "en": "Cancelled"},
    "cancelled_plan": {"ar": "(البيع ملغي)", "en": "(sale cancelled)"},
}


def filename(statement: CustomerInstallmentStatement) -> str:
    return f"installments-{statement.as_of}.pdf"


def render_html(statement: CustomerInstallmentStatement, language: Language, showroom_name: str) -> str:
    def t(key: str) -> str:
        return _L[key][language]

    def money(value: Decimal) -> str:
        return escape(format_money(value, statement.currency_code, language))

    sections = []
    for plan in statement.plans:
        rows = "".join(
            f"<tr><td>{i.seq}</td><td>{i.due_date}</td><td class='num'>{money(i.amount_due)}</td>"
            f"<td class='num'>{money(i.paid)}</td><td class='num'>{money(i.remaining)}</td>"
            f"<td class='{i.state.lower()}'>{t(i.state)}{f' ({i.days_late})' if i.days_late else ''}</td></tr>"
            for i in plan.installments
        )
        cancelled = f" {t('cancelled_plan')}" if plan.status == "CANCELLED" else ""
        sections.append(
            f"<h2>{t('sale')} {escape(plan.sale_no)} — {escape(plan.vehicle_label)} ({escape(plan.stock_no)}){cancelled}</h2>"
            f"<table><thead><tr><th>{t('seq')}</th><th>{t('due')}</th><th class='num'>{t('amount')}</th>"
            f"<th class='num'>{t('paid')}</th><th class='num'>{t('remaining')}</th><th>{t('state')}</th></tr></thead>"
            f"<tbody>{rows}</tbody></table>"
        )
    fonts = FONTS.as_uri()
    return f"""<!doctype html>
<html lang="{language}" dir="{"rtl" if language == "ar" else "ltr"}"><head><meta charset="utf-8"><style>
  @font-face {{ font-family: Plex; src: url('{fonts}/ibm-plex-sans-arabic-arabic-400-normal.woff'); font-weight: 400; }}
  @font-face {{ font-family: Plex; src: url('{fonts}/ibm-plex-sans-arabic-arabic-700-normal.woff'); font-weight: 700; }}
  @font-face {{ font-family: PlexLatin; src: url('{fonts}/ibm-plex-sans-arabic-latin-400-normal.woff'); font-weight: 400; }}
  @font-face {{ font-family: PlexLatin; src: url('{fonts}/ibm-plex-sans-arabic-latin-700-normal.woff'); font-weight: 700; }}
  @page {{ size: A4; margin: 14mm; @bottom-center {{ content: counter(page) " / " counter(pages); font-size: 8pt; }} }}
  body {{ font-family: PlexLatin, Plex, sans-serif; font-size: 9.5pt; color: #0f172a; }}
  h1 {{ font-size: 15pt; margin: 0 0 3mm; }}
  h2 {{ font-size: 11pt; margin: 6mm 0 2mm; }}
  table {{ width: 100%; border-collapse: collapse; }}
  th {{ background: #e2e8f0; text-align: start; padding: 1.5mm 2mm; }}
  td {{ border-bottom: 0.3pt solid #cbd5e1; padding: 1.2mm 2mm; }}
  .num {{ text-align: end; white-space: nowrap; }}
  .overdue {{ color: #b91c1c; font-weight: 700; }}
  .paid {{ color: #166534; }}
  .totals td {{ font-weight: 700; border: none; }}
</style></head><body>
  <h1>{escape(showroom_name)} — {t("title")}</h1>
  <p><b>{t("customer")}:</b> {escape(statement.customer_name)} {escape(statement.customer_phone or "")} &nbsp;
     <b>{t("as_of")}:</b> {statement.as_of}</p>
  <table class="totals"><tr>
    <td>{t("financed")}: {money(statement.total_financed)}</td><td>{t("paid")}: {money(statement.total_paid)}</td>
    <td>{t("remaining")}: {money(statement.total_remaining)}</td><td>{t("overdue")}: {money(statement.total_overdue)}</td>
  </tr></table>
  {"".join(sections)}
</body></html>"""


def render_pdf(statement: CustomerInstallmentStatement, language: Language, showroom_name: str) -> bytes:
    return html_to_pdf(render_html(statement, language, showroom_name))
