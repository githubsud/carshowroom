"""Printable consignment agreement (عقد أمانة, SPEC §4.4), consignor statement
and external showroom statement, Arabic and English.

Like the sale contract (D-80), the agreement records the parties, the car and
the agreed terms with signature lines, and contains no legal clauses (R-07);
the showroom adds its own terms if it needs them (Q-40).
"""

from decimal import Decimal
from html import escape
from typing import Any, Literal

from app.domain.consignment import ConsignorStatement, ExternalShowroomStatement, StatementLine
from app.domain.money import format_money
from app.reports.cash_book import FONTS, html_to_pdf

Language = Literal["ar", "en"]

_L: dict[str, dict[Language, str]] = {
    "agreement": {"ar": "اتفاق عرض سيارة بالأمانة", "en": "Vehicle consignment agreement"},
    "consignor_statement": {"ar": "كشف حساب صاحب سيارة أمانة", "en": "Consignor statement"},
    "showroom_statement": {"ar": "كشف حساب معرض", "en": "External showroom statement"},
    "date": {"ar": "التاريخ", "en": "Date"},
    "showroom": {"ar": "المعرض", "en": "Showroom"},
    "owner": {"ar": "صاحب السيارة", "en": "Owner"},
    "phone": {"ar": "الهاتف", "en": "Phone"},
    "cr": {"ar": "سجل تجاري", "en": "Commercial reg."},
    "vehicle": {"ar": "السيارة", "en": "Vehicle"},
    "stock_no": {"ar": "رقم المخزون", "en": "Stock no."},
    "vin": {"ar": "رقم الشاسيه", "en": "Chassis (VIN)"},
    "plate": {"ar": "رقم اللوحة", "en": "Plate"},
    "color": {"ar": "اللون", "en": "Colour"},
    "mileage": {"ar": "العداد (كم)", "en": "Mileage (km)"},
    "terms": {"ar": "شروط العرض", "en": "Terms"},
    "asking": {"ar": "سعر العرض", "en": "Asking price"},
    "NET_PRICE": {"ar": "صافي لصاحب السيارة", "en": "Net price to the owner"},
    "COMMISSION_FIXED": {"ar": "عمولة ثابتة للمعرض", "en": "Fixed commission to the showroom"},
    "COMMISSION_PCT": {"ar": "عمولة نسبة من سعر البيع", "en": "Commission, % of the sale price"},
    "expenses": {"ar": "مصاريف السيارة", "en": "Expenses on the car"},
    "OWNER": {"ar": "على صاحب السيارة وتُخصم من مستحقاته", "en": "Borne by the owner, deducted from the proceeds"},
    "SHOWROOM": {"ar": "على المعرض", "en": "Borne by the showroom"},
    "SHARED": {"ar": "مشتركة، نصيب صاحب السيارة", "en": "Shared; the owner's share"},
    "from": {"ar": "من", "en": "From"},
    "until": {"ar": "حتى", "en": "Until"},
    "open_end": {"ar": "مفتوحة", "en": "open-ended"},
    "notes": {"ar": "ملاحظات", "en": "Notes"},
    "sign_owner": {"ar": "توقيع صاحب السيارة", "en": "Owner signature"},
    "sign_showroom": {"ar": "توقيع المعرض", "en": "Showroom signature"},
    "as_of": {"ar": "حتى تاريخ", "en": "As of"},
    "entry": {"ar": "القيد", "en": "Entry"},
    "description": {"ar": "البيان", "en": "Description"},
    "debit": {"ar": "مدين", "en": "Debit"},
    "credit": {"ar": "دائن", "en": "Credit"},
    "balance": {"ar": "الرصيد", "en": "Balance"},
    "payable": {"ar": "مستحق له من المعرض", "en": "Owed to the owner"},
    "recoverable": {"ar": "مصاريف مستحقة عليه", "en": "Expenses owed by the owner"},
    "net": {"ar": "الصافي المستحق له", "en": "Net due to the owner"},
    "receivable": {"ar": "المستحق لنا عنده", "en": "Due to us"},
    "cars": {"ar": "السيارات", "en": "Cars"},
    "sent": {"ar": "أُرسلت", "en": "Sent"},
    "status": {"ar": "الحالة", "en": "Status"},
    "sale_price": {"ar": "سعر البيع", "en": "Sale price"},
    "OUT": {"ar": "لديه", "en": "With them"},
    "SOLD": {"ar": "مباعة", "en": "Sold"},
    "RETURNED": {"ar": "عادت", "en": "Returned"},
    "ACTIVE": {"ar": "معروضة", "en": "On display"},
}


def _style() -> str:
    fonts = FONTS.as_uri()
    return f"""<style>
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
  .ltr {{ direction: ltr; unicode-bidi: embed; }}
  .totals td {{ font-weight: 700; border: none; }}
  .signs {{ margin-top: 22mm; display: flex; justify-content: space-between; }}
  .signs div {{ width: 40%; border-top: 0.5pt solid #0f172a; padding-top: 2mm; text-align: center; }}
</style>"""


def _page(language: Language, body: str) -> str:
    direction = "rtl" if language == "ar" else "ltr"
    return f'<!doctype html><html lang="{language}" dir="{direction}"><head><meta charset="utf-8">{_style()}</head><body>{body}</body></html>'


def agreement_html(context: dict[str, Any], language: Language) -> str:
    def t(key: str) -> str:
        return _L[key][language]

    tenant, vehicle, owner = context["tenant"], context["vehicle"], context["owner"]
    c = context["consignment"]
    currency = tenant["currency_code"]

    def money(value: Decimal | None) -> str:
        return escape(format_money(value, currency, language)) if value is not None else "—"

    name = tenant["name_ar"] if language == "ar" else tenant["name_en"]
    if c.terms_type == "NET_PRICE":
        term_value = money(c.net_price_to_owner)
    elif c.terms_type == "COMMISSION_FIXED":
        term_value = money(c.commission_value)
    else:
        term_value = f"<span class='ltr'>{c.commission_value}%</span>"
    expenses = t(c.expenses_borne_by)
    if c.expenses_borne_by == "SHARED":
        expenses += f" <span class='ltr'>{c.shared_owner_pct}%</span>"
    label = " ".join(str(p) for p in (vehicle["make"], vehicle["model"], vehicle["trim"], vehicle["year"]) if p)
    rows = [
        (t("stock_no"), escape(vehicle["stock_no"])),
        (t("vehicle"), escape(label)),
        (t("vin"), f"<span class='ltr'>{escape(vehicle['vin'] or '—')}</span>"),
        (t("plate"), escape(vehicle["plate_no"] or "—")),
        (t("color"), escape(vehicle["color_ext"] or "—")),
        (t("mileage"), escape(str(vehicle["mileage_km"] or "—"))),
    ]
    vehicle_rows = "".join(f"<tr><th>{k}</th><td>{v}</td></tr>" for k, v in rows)
    period = f"{t('from')} {c.agreement_date} — {t('until')} {c.end_date or t('open_end')}"
    notes = f"<h2>{t('notes')}</h2><p>{escape(c.notes)}</p>" if c.notes else ""
    body = f"""
  <h1>{escape(name)} — {t("agreement")}</h1>
  <p><b>{t("date")}:</b> {c.agreement_date}</p>
  <table>
    <tr><th>{t("showroom")}</th><td>{escape(name)} {escape(tenant["address"] or "")}
        {f"— {t('cr')} {escape(tenant['commercial_reg_no'])}" if tenant["commercial_reg_no"] else ""}</td></tr>
    <tr><th>{t("owner")}</th><td>{escape(owner.name)} — {t("phone")}:
        <span class='ltr'>{escape(owner.phone_primary or "—")}</span></td></tr>
  </table>
  <h2>{t("vehicle")}</h2>
  <table>{vehicle_rows}</table>
  <h2>{t("terms")}</h2>
  <table>
    <tr><th>{t(c.terms_type)}</th><td>{term_value}</td></tr>
    <tr><th>{t("asking")}</th><td>{money(vehicle["asking_price"])}</td></tr>
    <tr><th>{t("expenses")}</th><td>{expenses}</td></tr>
    <tr><th>{t("date")}</th><td>{period}</td></tr>
  </table>
  {notes}
  <div class="signs"><div>{t("sign_owner")}</div><div>{t("sign_showroom")}</div></div>
"""
    return _page(language, body)


def _lines_table(lines: list[StatementLine], money: Any, t: Any) -> str:
    rows = "".join(
        f"<tr><td>{line.entry_date}</td><td>{line.entry_no}</td><td>{escape(line.description)}"
        f"{f' ({escape(line.stock_no)})' if line.stock_no else ''}</td>"
        f"<td class='num'>{money(line.debit) if line.debit else ''}</td>"
        f"<td class='num'>{money(line.credit) if line.credit else ''}</td><td class='num'>{money(line.balance)}</td></tr>"
        for line in lines
    )
    return (
        f"<table><thead><tr><th>{t('date')}</th><th>{t('entry')}</th><th>{t('description')}</th>"
        f"<th class='num'>{t('debit')}</th><th class='num'>{t('credit')}</th><th class='num'>{t('balance')}</th>"
        f"</tr></thead><tbody>{rows}</tbody></table>"
    )


def consignor_statement_html(statement: ConsignorStatement, language: Language, showroom_name: str) -> str:
    def t(key: str) -> str:
        return _L[key][language]

    def money(value: Decimal) -> str:
        return escape(format_money(value, statement.currency_code, language))

    body = f"""
  <h1>{escape(showroom_name)} — {t("consignor_statement")}</h1>
  <p><b>{t("owner")}:</b> {escape(statement.consignor_name)}
     <span class='ltr'>{escape(statement.consignor_phone or "")}</span> &nbsp; <b>{t("as_of")}:</b> {statement.as_of}</p>
  <table class="totals"><tr>
    <td>{t("payable")}: {money(statement.payable)}</td><td>{t("recoverable")}: {money(statement.recoverable)}</td>
    <td>{t("net")}: {money(statement.net_due_to_owner)}</td>
  </tr></table>
  {_lines_table(statement.lines, money, t)}
"""
    return _page(language, body)


def showroom_statement_html(statement: ExternalShowroomStatement, language: Language, showroom_name: str) -> str:
    def t(key: str) -> str:
        return _L[key][language]

    def money(value: Decimal | None) -> str:
        return escape(format_money(value, statement.currency_code, language)) if value is not None else ""

    cars = "".join(
        f"<tr><td>{escape(c.stock_no)}</td><td>{escape(c.vehicle_label)}</td><td>{c.sent_date}</td>"
        f"<td>{t(c.status)}</td><td class='num'>{money(c.sale_price)}</td></tr>"
        for c in statement.cars
    )
    body = f"""
  <h1>{escape(showroom_name)} — {t("showroom_statement")}</h1>
  <p><b>{t("showroom")}:</b> {escape(statement.name)} <span class='ltr'>{escape(statement.phone or "")}</span>
     &nbsp; <b>{t("as_of")}:</b> {statement.as_of}</p>
  <table class="totals"><tr><td>{t("receivable")}: {money(statement.receivable)}</td></tr></table>
  {_lines_table(statement.lines, money, t)}
  <h2>{t("cars")}</h2>
  <table><thead><tr><th>{t("stock_no")}</th><th>{t("vehicle")}</th><th>{t("sent")}</th><th>{t("status")}</th>
    <th class='num'>{t("sale_price")}</th></tr></thead><tbody>{cars}</tbody></table>
"""
    return _page(language, body)


def pdf(html: str) -> bytes:
    return html_to_pdf(html)
