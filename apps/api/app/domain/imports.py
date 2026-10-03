"""Excel import (SPEC §4.13, BACKLOG 8.x): field catalogue, header synonyms and
tolerant parsers for numbers and dates as showrooms really type them.

Pure functions, unit-tested in tests/unit/test_import_parsing.py.
"""

import re
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.domain.money import CENT, Money
from app.domain.vehicles import StrictModel

ImportKind = Literal["VEHICLES", "CUSTOMERS", "PARTNERS", "INSTALLMENTS", "CASH"]
KINDS: tuple[ImportKind, ...] = ("VEHICLES", "CUSTOMERS", "PARTNERS", "INSTALLMENTS", "CASH")
FieldType = Literal["text", "money", "date", "year", "int", "percent", "phone"]


class ParseError(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class FieldSpec(BaseModel):
    key: str
    type: FieldType
    required: bool = False
    # Several columns may map to it (vehicle expenses: one line each, memo = the header).
    multiple: bool = False
    label_ar: str
    label_en: str
    synonyms: list[str]


def _f(key: str, kind: FieldType, ar: str, en: str, synonyms: list[str], **extra: Any) -> FieldSpec:
    return FieldSpec(key=key, type=kind, label_ar=ar, label_en=en, synonyms=[ar, en, *synonyms], **extra)


FIELDS: dict[ImportKind, list[FieldSpec]] = {
    "VEHICLES": [
        _f(
            "make", "text", "الماركة", "Make", ["ماركه", "النوع", "نوع السياره", "brand", "manufacturer"], required=True
        ),
        _f(
            "model",
            "text",
            "الموديل",
            "Model",
            ["موديل", "الطراز"],
            required=True,
        ),
        _f("year", "year", "سنة الصنع", "Year", ["السنه", "سنه", "سنه الصنع", "موديل سنه", "model year"]),
        _f("trim", "text", "الفئة", "Trim", ["فئه"]),
        _f("color", "text", "اللون", "Colour", ["لون", "color"]),
        _f("vin", "text", "رقم الشاسيه", "VIN", ["الشاسيه", "شاسيه", "رقم الشاسي", "chassis", "chassis no"]),
        _f("plate_no", "text", "رقم اللوحة", "Plate", ["اللوحه", "لوحه", "النمره", "رقم اللوحه", "plate no"]),
        _f("mileage_km", "int", "العداد", "Mileage", ["الكيلومترات", "كم", "km", "odometer", "العداد كم"]),
        _f("asking_price", "money", "سعر العرض", "Asking price", ["سعر البيع", "السعر المطلوب", "price"]),
        _f("purchase_date", "date", "تاريخ الشراء", "Purchase date", ["تاريخ الدخول", "تاريخ الاستلام", "date"]),
        _f(
            "purchase_price",
            "money",
            "سعر الشراء",
            "Purchase price",
            ["الشراء", "التكلفه", "ثمن الشراء", "cost"],
            required=True,
        ),
        _f(
            "expense",
            "money",
            "مصاريف",
            "Expense",
            [
                "مصروفات",
                "صيانه",
                "سمكره",
                "دهان",
                "تلميع",
                "غسيل",
                "نقل",
                "فحص",
                "تجديد رخصه",
                "رخصه",
                "اكراميه",
                "maintenance",
                "transport",
                "paint",
                "bodywork",
                "license",
                "inspection",
                "expenses",
            ],
            multiple=True,
        ),
        _f("seller_name", "text", "البائع", "Seller", ["اسم البائع", "seller name"]),
        _f("seller_phone", "phone", "موبايل البائع", "Seller phone", ["تليفون البائع"]),
        _f("owed_to_seller", "money", "باقي للبائع", "Owed to seller", ["متبقي للبائع", "المتبقي للبائع"]),
        _f("notes", "text", "ملاحظات", "Notes", ["ملاحظه", "notes", "remarks"]),
    ],
    "CUSTOMERS": [
        _f(
            "name",
            "text",
            "الاسم",
            "Name",
            ["اسم العميل", "العميل", "customer", "customer name"],
            required=True,
        ),
        _f("phone", "phone", "الموبايل", "Phone", ["التليفون", "الهاتف", "رقم الموبايل", "تليفون", "mobile"]),
        _f("national_id", "text", "الرقم القومي", "National ID", ["رقم البطاقه", "البطاقه", "id"]),
        _f("address", "text", "العنوان", "Address", []),
        _f("notes", "text", "ملاحظات", "Notes", ["ملاحظه"]),
    ],
    "PARTNERS": [
        _f(
            "name",
            "text",
            "الاسم",
            "Name",
            ["اسم الشريك", "الشريك", "partner"],
            required=True,
        ),
        _f("phone", "phone", "الموبايل", "Phone", ["التليفون", "الهاتف"]),
        _f(
            "percentage",
            "percent",
            "النسبة",
            "Share %",
            ["نسبه", "النسبه", "نسبه الملكيه", "%", "share"],
            required=True,
        ),
        _f("capital", "money", "رأس المال", "Capital", ["راس المال", "راسمال", "المساهمه"]),
        _f("current_balance", "money", "الحساب الجاري", "Current account", ["جاري", "رصيد جاري", "ارباح غير مسحوبه"]),
        _f("loan_to_partner", "money", "سلفة على الشريك", "Loan to partner", ["سلفه", "عليه"]),
        _f("loan_from_partner", "money", "قرض من الشريك", "Loan from partner", ["له", "قرض"]),
    ],
    "INSTALLMENTS": [
        _f(
            "customer_name",
            "text",
            "العميل",
            "Customer",
            ["اسم العميل", "الاسم", "customer name"],
            required=True,
        ),
        _f("customer_phone", "phone", "الموبايل", "Phone", ["التليفون", "الهاتف", "موبايل العميل"]),
        _f("reference", "text", "رقم العقد", "Contract", ["العقد", "رقم البيع", "المرجع", "reference"]),
        _f("vehicle", "text", "السيارة", "Vehicle", ["العربيه", "السياره", "car"]),
        _f(
            "due_date",
            "date",
            "تاريخ الاستحقاق",
            "Due date",
            ["الاستحقاق", "تاريخ القسط", "due"],
            required=True,
        ),
        _f(
            "amount",
            "money",
            "قيمة القسط",
            "Amount",
            ["القسط", "المبلغ", "قيمه"],
            required=True,
        ),
        _f("paid", "money", "المدفوع", "Paid", ["مدفوع", "المسدد"]),
    ],
    "CASH": [
        _f(
            "account_name",
            "text",
            "الحساب",
            "Account",
            ["اسم الحساب", "الخزنه", "البنك", "account name"],
            required=True,
        ),
        _f("account_type", "text", "النوع", "Type", ["نوع الحساب", "type"]),
        _f(
            "balance",
            "money",
            "الرصيد",
            "Balance",
            ["رصيد", "المبلغ", "opening balance"],
            required=True,
        ),
    ],
}

_SHEET_HINTS: dict[ImportKind, list[str]] = {
    "VEHICLES": ["عربيات", "سيارات", "مخزون", "vehicles", "cars", "stock", "inventory"],
    "CUSTOMERS": ["عملاء", "العملاء", "customers", "clients"],
    "PARTNERS": ["شركاء", "الشركاء", "partners"],
    "INSTALLMENTS": ["اقساط", "الاقساط", "installments"],
    "CASH": ["خزنه", "الخزنه", "بنوك", "البنك", "نقديه", "cash", "bank"],
}

# --- Text normalisation --------------------------------------------------------------------------------

_DIACRITICS = re.compile("[ً-ْٰـ]")  # harakat and tatweel
_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")


def to_western_digits(text: str) -> str:
    return text.translate(_DIGITS).replace("٫", ".").replace("٬", ",")


def normalize_header(text: Any) -> str:
    value = str(text or "").strip().lower()
    value = _DIACRITICS.sub("", value)
    value = re.sub("[أإآ]", "ا", value).replace("ة", "ه").replace("ى", "ي")
    value = re.sub(r"[^\w%\s]", " ", value)
    return re.sub(r"\s+", " ", value).strip()


_SYNONYMS: dict[ImportKind, list[tuple[str, FieldSpec]]] = {
    kind: [(normalize_header(s), spec) for spec in specs for s in spec.synonyms] for kind, specs in FIELDS.items()
}


def _match(header: str, kind: ImportKind) -> FieldSpec | None:
    key = normalize_header(header)
    if not key:
        return None
    for synonym, spec in _SYNONYMS[kind]:
        if key == synonym:
            return spec
    return None


def suggest_mapping(headers: list[str], kind: ImportKind) -> list[str | None]:
    """One field per column (or None to ignore); single fields are used once."""
    used: set[str] = set()
    result: list[str | None] = []
    for header in headers:
        spec = _match(header, kind)
        if spec is None or (spec.key in used and not spec.multiple):
            result.append(None)
            continue
        used.add(spec.key)
        result.append(spec.key)
    return result


def detect_header_row(rows: list[list[Any]], *, scan: int = 15) -> int:
    """The row with the most recognised headers among the first rows; otherwise
    the first row with at least two filled cells."""
    best, best_score = -1, 0
    for index, row in enumerate(rows[:scan]):
        score = max(sum(1 for cell in row if cell is not None and _match(str(cell), kind)) for kind in KINDS)
        if score > best_score:
            best, best_score = index, score
    if best >= 0:
        return best
    for index, row in enumerate(rows[:scan]):
        if sum(1 for cell in row if cell not in (None, "")) >= 2:
            return index
    return 0


def detect_kind(headers: list[str], sheet_name: str = "") -> ImportKind:
    name = normalize_header(sheet_name)
    scores = {kind: sum(1 for h in headers if _match(h, kind)) for kind in KINDS}
    for kind, hints in _SHEET_HINTS.items():
        if any(normalize_header(h) in name for h in hints):
            scores[kind] += 3
    # Ties keep the catalogue order (vehicles first: the usual sheet).
    return max(KINDS, key=lambda kind: scores[kind])


# --- Values ----------------------------------------------------------------------------------------------

_CURRENCY = re.compile(
    r"(ج\.?\s*م\.?|جنيه(ا)?|جم|egp|le|l\.e\.?|ر\.?\s*ق\.?|ريال|qar|qr|sar|aed|usd|\$|£|€)", re.IGNORECASE
)


def parse_number(raw: Any) -> Decimal:
    """Arabic-Indic digits, 'EGP 15,000', '400.000,75', '(1,250)' -> Decimal with 2 places."""
    if isinstance(raw, int | float | Decimal) and not isinstance(raw, bool):
        value = Decimal(str(raw))
    else:
        text = to_western_digits(str(raw)).strip()
        text = _CURRENCY.sub("", text).replace(" ", "").replace(" ", "")
        negative = False
        if text.startswith("(") and text.endswith(")"):
            negative, text = True, text[1:-1]
        if text.endswith("-") and text.count("-") == 1:
            negative, text = True, text[:-1]
        if text.startswith("-") and text.count("-") == 1:
            negative, text = True, text[1:]
        if not re.fullmatch(r"[0-9.,]+", text or "x"):
            raise ParseError("BAD_NUMBER")
        if "," in text and "." in text:
            # The later separator is the decimal one.
            if text.rfind(",") > text.rfind("."):
                text = text.replace(".", "").replace(",", ".")
            else:
                text = text.replace(",", "")
        elif "," in text:
            parts = text.split(",")
            if len(parts) == 2 and len(parts[1]) != 3:
                text = text.replace(",", ".")  # decimal comma: 12,5
            elif all(len(p) == 3 for p in parts[1:]):
                text = text.replace(",", "")
            else:
                raise ParseError("BAD_NUMBER")
        if text.count(".") > 1:
            raise ParseError("BAD_NUMBER")
        try:
            value = Decimal(text)
        except InvalidOperation as exc:
            raise ParseError("BAD_NUMBER") from exc
        if negative:
            value = -value
    if value != value.quantize(CENT):
        raise ParseError("BAD_NUMBER")
    return value.quantize(CENT)


_EXCEL_EPOCH = date(1899, 12, 30)


def parse_date(raw: Any) -> date:
    """ISO, d/m/y (and - or .), y/m/d, two-digit years, Arabic digits, Excel serials."""
    if isinstance(raw, datetime):
        return raw.date()
    if isinstance(raw, date):
        return raw
    text = to_western_digits(str(raw)).strip()
    try:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}(T.*)?", text):
            return date.fromisoformat(text[:10])
        if re.fullmatch(r"\d{4,5}(\.0+)?", text):
            serial = int(float(text))
            if 20000 <= serial <= 80000:
                return _EXCEL_EPOCH + timedelta(days=serial)
            raise ParseError("BAD_DATE")
        match = re.fullmatch(r"(\d{4})[/.\-](\d{1,2})[/.\-](\d{1,2})", text)
        if match:
            y, m, d = (int(g) for g in match.groups())
            return date(y, m, d)
        match = re.fullmatch(r"(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{2}|\d{4})", text)
        if match:
            d, m, y = (int(g) for g in match.groups())
            return date(y + 2000 if y < 100 else y, m, d)
    except ValueError as exc:
        raise ParseError("BAD_DATE") from exc
    raise ParseError("BAD_DATE")


# --- API models --------------------------------------------------------------------------------------------


class SheetIn(BaseModel):
    """A sheet given as data (the onboarding wizard), headers = field keys."""

    name: str
    kind: ImportKind
    headers: list[str]
    rows: list[list[str | None]] = Field(max_length=5000)


class ImportCreateIn(StrictModel):
    go_live_date: date
    file_name: str | None = None
    # An .xlsx or .csv file, base64-encoded (max ~5 MB).
    content_base64: str | None = Field(default=None, max_length=7_000_000)
    sheets: list[SheetIn] = Field(default_factory=list, max_length=10)


class SheetMappingIn(StrictModel):
    index: int
    kind: ImportKind | None = None
    column_map: list[str | None]
    skip: bool = False
    remember: bool = True


class ImportMappingIn(StrictModel):
    sheets: list[SheetMappingIn]


class RowError(BaseModel):
    field: str | None
    code: str


class RowResult(BaseModel):
    row_no: int
    errors: list[RowError]


class SheetOut(BaseModel):
    index: int
    name: str
    kind: ImportKind
    skip: bool
    header_row: int
    headers: list[str]
    sample_rows: list[list[str | None]]
    row_count: int
    column_map: list[str | None]
    mapping_remembered: bool
    ok_rows: int | None = None
    error_rows: list[RowResult] | None = None


class ImportJobOut(BaseModel):
    id: UUID
    file_name: str | None
    go_live_date: date
    status: Literal["UPLOADED", "VALIDATED", "COMMITTED"]
    sheets: list[SheetOut]
    fields: dict[str, list[FieldSpec]]
    opening_total: Money | None = None
    result: dict[str, Any] | None = None
    entry_no: int | None = None
    created_at: datetime


class OpeningEquityOut(BaseModel):
    """What is left on 3900 Opening balance equity (Q-16) and who can take it."""

    balance: Money
    partners: list[dict[str, Any]]


class EquityClearingLine(StrictModel):
    partner_id: UUID
    account: Literal["CAPITAL", "CURRENT"]
    amount: Money


class EquityClearingIn(StrictModel):
    clearing_date: date
    lines: list[EquityClearingLine] = Field(min_length=1, max_length=50)
