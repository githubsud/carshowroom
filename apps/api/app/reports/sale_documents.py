"""Printable sale invoice and sale contract (SPEC §4.7, §4.14), Arabic and English.

No tax lines (D-39) and no legal clauses (R-07): the contract records the
parties, the car, the price and how it was paid, with signature lines. The
showroom adds its own terms if it needs them.
"""

from decimal import Decimal
from html import escape
from typing import Any, Literal

from app.domain.money import format_money
from app.reports.cash_book import FONTS, html_to_pdf

Language = Literal["ar", "en"]
Kind = Literal["invoice", "contract"]

_L: dict[str, dict[Language, str]] = {
    "invoice": {"ar": "فاتورة بيع سيارة", "en": "Vehicle sale invoice"},
    "contract": {"ar": "عقد بيع سيارة", "en": "Vehicle sale contract"},
    "invoice_no": {"ar": "رقم الفاتورة", "en": "Invoice no."},
    "sale_no": {"ar": "رقم البيع", "en": "Sale no."},
    "date": {"ar": "التاريخ", "en": "Date"},
    "seller": {"ar": "البائع", "en": "Seller"},
    "buyer": {"ar": "المشتري", "en": "Buyer"},
    "phone": {"ar": "الهاتف", "en": "Phone"},
    "cr": {"ar": "سجل تجاري", "en": "Commercial reg."},
    "vehicle": {"ar": "السيارة", "en": "Vehicle"},
    "stock_no": {"ar": "رقم المخزون", "en": "Stock no."},
    "vin": {"ar": "رقم الشاسيه", "en": "Chassis (VIN)"},
    "plate": {"ar": "رقم اللوحة", "en": "Plate"},
    "color": {"ar": "اللون", "en": "Colour"},
    "mileage": {"ar": "العداد (كم)", "en": "Mileage (km)"},
    "list_price": {"ar": "السعر", "en": "Price"},
    "discount": {"ar": "الخصم", "en": "Discount"},
    "total": {"ar": "الإجمالي", "en": "Total"},
    "payments": {"ar": "طريقة السداد", "en": "Payment"},
    "deposit": {"ar": "عربون مدفوع مسبقاً", "en": "Deposit paid earlier"},
    "trade_in": {"ar": "سيارة مستبدلة", "en": "Trade-in vehicle"},
    "markup": {"ar": "فرق سعر التقسيط", "en": "Installment price difference"},
    "deferred_total": {"ar": "الثمن الإجمالي (بيع بالتقسيط)", "en": "Total price (installment sale)"},
    "installments": {"ar": "الباقي على {n} قسط، أولها {first}", "en": "The rest in {n} installments from {first}"},
    "fixed_price": {
        "ar": "الثمن المذكور متفق عليه عند العقد وثابت، ولا يزيد بأي حال عند التأخر في السداد.",
        "en": "The price above is agreed at the contract and fixed; it never increases if a payment is late.",
    },
    "sign_seller": {"ar": "توقيع البائع", "en": "Seller signature"},
    "sign_buyer": {"ar": "توقيع المشتري", "en": "Buyer signature"},
    "contract_text": {
        "ar": "باع الطرف الأول (البائع) إلى الطرف الثاني (المشتري) السيارة الموضحة أعلاه بالسعر والسداد المبينين.",
        "en": "The first party (seller) has sold to the second party (buyer) the vehicle described above "
        "for the price and payment shown.",
    },
}


def filename(context: dict[str, Any], kind: Kind) -> str:
    sale = context["sale"]
    return f"{kind}-{sale['invoice_no'] or sale['sale_no']}.pdf"


def render_html(context: dict[str, Any], kind: Kind, language: Language, logo_url: str | None = None) -> str:
    sale, tenant, vehicle = context["sale"], context["tenant"], context["vehicle"]
    currency = tenant["currency_code"]

    def t(key: str) -> str:
        return _L[key][language]

    def money(value: Decimal) -> str:
        return escape(format_money(Decimal(value), currency, language))

    def row(label: str, value: object) -> str:
        return f"<tr><th>{label}</th><td>{escape(str(value)) if value not in (None, '') else '—'}</td></tr>"

    showroom = tenant["name_ar"] if language == "ar" else tenant["name_en"]
    vehicle_name = " ".join(str(p) for p in (vehicle["make"], vehicle["model"], vehicle["trim"], vehicle["year"]) if p)
    lines = [
        f"<tr><td>{escape(p['cash_account_name_ar'] if language == 'ar' else (p['cash_account_name_en'] or p['cash_account_name_ar']))}"
        f"{' — ' + escape(p['reference']) if p['reference'] else ''}</td><td class='num'>{money(p['amount'])}</td></tr>"
        for p in context["payments"]
    ]
    if Decimal(sale["deposit_applied"]) > 0:
        lines.append(f"<tr><td>{t('deposit')}</td><td class='num'>{money(sale['deposit_applied'])}</td></tr>")
    trade_in = context["trade_in"]
    if trade_in is not None:
        label = " ".join(str(p) for p in (trade_in.make, trade_in.model, trade_in.year) if p)
        lines.append(
            f"<tr><td>{t('trade_in')}: {escape(label)} {escape(trade_in.vin or '')}</td>"
            f"<td class='num'>{money(trade_in.agreed_value)}</td></tr>"
        )
    # An installment sale is one agreed deferred price (docs/SHARIA.md): show it whole.
    plan = sale.get("installment_plan") or None
    markup = Decimal(str(plan.get("markup") or 0)) if plan else Decimal(0)
    if plan and Decimal(sale["receivable_amount"]) > 0:
        schedule = plan.get("schedule") or []
        count = plan.get("count") or len(schedule)
        first = plan.get("first_due_date") or (schedule[0]["due_date"] if schedule else "")
        lines.append(
            f"<tr><td>{escape(t('installments').format(n=count, first=first))}</td>"
            f"<td class='num'>{money(sale['receivable_amount'])}</td></tr>"
        )
    total_price = Decimal(sale["sale_price"]) + markup
    fixed = f"<p class='terms'>{t('fixed_price')}</p>" if plan else ""
    logo = f"<img class='logo' src='{escape(logo_url)}'>" if logo_url else ""
    contract = (
        f"<p class='terms'>{t('contract_text')}</p>{fixed}"
        f"<table class='signatures'><tr><td>{t('sign_seller')}</td><td>{t('sign_buyer')}</td></tr></table>"
        if kind == "contract"
        else ""
    )
    fonts = FONTS.as_uri()
    return f"""<!doctype html>
<html lang="{language}" dir="{"rtl" if language == "ar" else "ltr"}"><head><meta charset="utf-8"><style>
  @font-face {{ font-family: Plex; src: url('{fonts}/ibm-plex-sans-arabic-arabic-400-normal.woff'); font-weight: 400; }}
  @font-face {{ font-family: Plex; src: url('{fonts}/ibm-plex-sans-arabic-arabic-700-normal.woff'); font-weight: 700; }}
  @font-face {{ font-family: PlexLatin; src: url('{fonts}/ibm-plex-sans-arabic-latin-400-normal.woff'); font-weight: 400; }}
  @font-face {{ font-family: PlexLatin; src: url('{fonts}/ibm-plex-sans-arabic-latin-700-normal.woff'); font-weight: 700; }}
  @page {{ size: A4; margin: 16mm; }}
  body {{ font-family: PlexLatin, Plex, sans-serif; font-size: 10pt; color: #0f172a; }}
  header {{ display: flex; justify-content: space-between; align-items: center; border-bottom: 1pt solid #0f172a; }}
  .logo {{ max-height: 18mm; }}
  h1 {{ font-size: 16pt; margin: 4mm 0; }}
  h2 {{ font-size: 11pt; margin: 5mm 0 2mm; }}
  table {{ width: 100%; border-collapse: collapse; }}
  th {{ text-align: start; width: 35%; color: #475569; font-weight: 400; padding: 1.2mm 0; }}
  td {{ padding: 1.2mm 0; }}
  .money td {{ border-bottom: 0.3pt solid #cbd5e1; }}
  .num {{ text-align: end; white-space: nowrap; }}
  .grand td {{ font-weight: 700; border-top: 1pt solid #0f172a; }}
  .terms {{ margin-top: 8mm; }}
  .signatures td {{ padding-top: 20mm; border-bottom: none; width: 50%; }}
</style></head><body>
  <header><div><b>{escape(showroom)}</b><br>{escape(tenant["address"] or "")}<br>
    {escape(" / ".join(tenant["phones"] or []))}
    {"<br>" + t("cr") + ": " + escape(tenant["commercial_reg_no"]) if tenant["commercial_reg_no"] else ""}</div>{logo}</header>
  <h1>{t(kind)}</h1>
  <table>
    {row(t("invoice_no"), sale["invoice_no"])}{row(t("sale_no"), sale["sale_no"])}{row(t("date"), sale["sale_date"])}
    {row(t("buyer"), sale["buyer_name"])}{row(t("phone"), sale["buyer_phone"])}
  </table>
  <h2>{t("vehicle")}</h2>
  <table>
    {row(t("vehicle"), vehicle_name)}{row(t("stock_no"), vehicle["stock_no"])}{row(t("vin"), vehicle["vin"])}
    {row(t("plate"), vehicle["plate_no"])}{row(t("color"), vehicle["color_ext"])}{row(t("mileage"), vehicle["mileage_km"])}
  </table>
  <h2>{t("total")}</h2>
  <table class="money">
    <tr><td>{t("list_price")}</td><td class="num">{money(sale["list_price"])}</td></tr>
    {f'<tr><td>{t("discount")}</td><td class="num">{money(sale["discount"])}</td></tr>' if Decimal(sale["discount"]) > 0 else ""}
    {f'<tr><td>{t("markup")}</td><td class="num">{money(markup)}</td></tr>' if markup > 0 else ""}
    <tr class="grand"><td>{t("deferred_total") if markup > 0 else t("total")}</td><td class="num">{money(total_price)}</td></tr>
  </table>
  <h2>{t("payments")}</h2>
  <table class="money">{"".join(lines)}</table>
  {contract}
</body></html>"""


def render_pdf(context: dict[str, Any], kind: Kind, language: Language, logo_url: str | None = None) -> bytes:
    return html_to_pdf(render_html(context, kind, language, logo_url))
