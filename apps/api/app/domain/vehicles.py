"""Request and response models for customers, suppliers, locations, vehicles,
purchases, vehicle expenses, media and documents (SPEC §4.3, §4.6, §4.10).

Cost data (purchase price, expenses, total cost, profit) and the minimum price
are optional fields that are dropped from responses for users without
vehicle.view_cost / vehicle.view_min_price (ARCHITECTURE §5): see
``COST_FIELDS`` and app.api.masking.
"""

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from app.domain.money import Money, PositiveMoney

NameText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
ShortText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=60)]
NoteText = Annotated[str, StringConstraints(strip_whitespace=True, max_length=1000)]
ReasonText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=500)]
NationalId = Annotated[str, StringConstraints(strip_whitespace=True, pattern=r"^[0-9A-Za-z]{4,20}$")]
PhoneInput = Annotated[str, StringConstraints(strip_whitespace=True, min_length=6, max_length=25)]
VinText = Annotated[str, StringConstraints(strip_whitespace=True, max_length=40)]

VehicleStatus = Literal[
    "DRAFT",
    "IN_PREPARATION",
    "AVAILABLE",
    "RESERVED",
    "SOLD",
    "DELIVERED",
    "AT_OTHER_SHOWROOM",
    "RETURNED_TO_OWNER",
    "ARCHIVED",
]
Transmission = Literal["AUTOMATIC", "MANUAL", "CVT", "OTHER"]
Fuel = Literal["PETROL", "DIESEL", "HYBRID", "ELECTRIC", "NATURAL_GAS", "OTHER"]
AcquisitionSource = Literal["DIRECT_PURCHASE", "TRADE_IN", "CONSIGNMENT_IN", "AUCTION", "IMPORT"]
Aging = Literal["FRESH", "AGING", "OLD", "STALE"]
LocationType = Literal["BRANCH_YARD", "OUTDOOR_LOT", "WORKSHOP", "EXTERNAL_SHOWROOM", "CUSTOMER"]
SupplierKind = Literal["WORKSHOP", "TRANSPORT", "PARTS", "AD_AGENCY", "OTHER"]
FundingKind = Literal["CASH_ACCOUNT", "SUPPLIER_CREDIT", "PARTNER"]
PartnerFundingMode = Literal["CURRENT_ACCOUNT", "LOAN"]
DocumentEntity = Literal["VEHICLE", "CUSTOMER", "SALE", "SUPPLIER"]
DocumentType = Literal[
    "LICENSE", "PURCHASE_CONTRACT", "SELLER_RECEIPT", "INSPECTION_REPORT", "SALE_CONTRACT", "ID_COPY", "OTHER"
]
ImageType = Literal["image/webp", "image/jpeg", "image/png"]
DocumentContentType = Literal["application/pdf", "image/webp", "image/jpeg", "image/png"]

# Cost-bearing keys, dropped for users without vehicle.view_cost (ARCHITECTURE §5).
COST_FIELDS = frozenset({"cost", "total_cost", "cost_complete", "missing_categories", "profit", "purchase"})
MIN_PRICE_FIELD = "min_price"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


# --- Customers -------------------------------------------------------------------------


class CustomerIn(StrictModel):
    name: NameText
    phone: PhoneInput | None = None
    other_phones: list[PhoneInput] = Field(default_factory=list, max_length=5)
    national_id: NationalId | None = None
    is_buyer: bool = False
    is_seller: bool = False
    address: NoteText | None = None
    notes: NoteText | None = None


class CustomerUpdate(StrictModel):
    name: NameText | None = None
    phone: PhoneInput | None = None
    other_phones: list[PhoneInput] | None = Field(default=None, max_length=5)
    national_id: NationalId | None = None
    is_buyer: bool | None = None
    is_seller: bool | None = None
    address: NoteText | None = None
    notes: NoteText | None = None
    archived: bool | None = None


class CustomerOut(BaseModel):
    id: UUID
    name: str
    phone_primary: str | None
    phones: list[str]
    national_id_masked: str | None
    is_buyer: bool
    is_seller: bool
    is_consignor: bool
    address: str | None
    notes: str | None
    archived: bool
    created_at: datetime


class SellerPayable(BaseModel):
    vehicle_id: UUID
    stock_no: str
    vehicle_label: str
    outstanding: Money


class CustomerBalances(BaseModel):
    """Money the showroom holds for, or owes to, the customer (cash.view)."""

    deposits_held: Money
    credit_owed: Money


class CustomerDetail(BaseModel):
    customer: CustomerOut
    balances: CustomerBalances | None = None
    # Deferred purchase prices reveal cost (vehicle.view_cost).
    seller_payables: list[SellerPayable] | None = None


class NationalIdOut(BaseModel):
    national_id: str


class CustomerRefundIn(StrictModel):
    refund_date: date
    amount: PositiveMoney
    cash_account_id: UUID
    notes: NoteText | None = None


class CustomerRefundOut(BaseModel):
    id: UUID
    customer_id: UUID
    refund_date: date
    amount: Money
    cash_account_id: UUID
    status: Literal["POSTED", "REVERSED"]
    entry_no: int


# --- Suppliers ------------------------------------------------------------------------------


class SupplierIn(StrictModel):
    name: NameText
    kind: SupplierKind = "OTHER"
    phone: PhoneInput | None = None
    notes: NoteText | None = None


class SupplierUpdate(StrictModel):
    name: NameText | None = None
    kind: SupplierKind | None = None
    phone: PhoneInput | None = None
    notes: NoteText | None = None
    archived: bool | None = None


class SupplierOut(BaseModel):
    id: UUID
    name: str
    kind: SupplierKind
    phone: str | None
    notes: str | None
    archived: bool
    # What the showroom owes the supplier (payable to suppliers, rule 31).
    balance: Money


class SupplierPaymentIn(StrictModel):
    payment_date: date
    amount: PositiveMoney
    cash_account_id: UUID
    notes: NoteText | None = None


class SupplierPaymentOut(BaseModel):
    id: UUID
    supplier_id: UUID
    payment_date: date
    amount: Money
    cash_account_id: UUID
    status: Literal["POSTED", "REVERSED"]
    entry_no: int


class StatementRow(BaseModel):
    entry_date: date
    entry_no: int
    description: str
    source_type: str
    # Owed more (a purchase on credit) / owed less (a payment).
    amount_owed: Money
    amount_paid: Money
    balance: Money
    reversed: bool
    is_reversal: bool


class SupplierStatementOut(BaseModel):
    supplier: SupplierOut
    date_from: date
    date_to: date
    currency_code: str
    opening_balance: Money
    closing_balance: Money
    lines: list[StatementRow]


# --- Locations --------------------------------------------------------------------------------


class LocationIn(StrictModel):
    type: LocationType
    name_ar: NameText
    name_en: NameText | None = None
    is_default: bool = False


class LocationUpdate(StrictModel):
    name_ar: NameText | None = None
    name_en: NameText | None = None
    is_default: bool | None = None
    archived: bool | None = None


class LocationOut(BaseModel):
    id: UUID
    type: LocationType
    name_ar: str
    name_en: str | None
    is_default: bool
    archived: bool


# --- Vehicles -----------------------------------------------------------------------------------


class _VehicleFields(StrictModel):
    vin: VinText | None = None
    plate_no: ShortText | None = None
    make: NameText | None = None
    model: NameText | None = None
    trim: ShortText | None = None
    year: int | None = Field(default=None, ge=1950, le=2100)
    color_ext: ShortText | None = None
    color_int: ShortText | None = None
    body_type: ShortText | None = None
    transmission: Transmission | None = None
    fuel: Fuel | None = None
    engine_cc: int | None = Field(default=None, ge=0, le=20000)
    mileage_km: int | None = Field(default=None, ge=0, le=5_000_000)
    license_expiry: date | None = None
    license_governorate: ShortText | None = None
    asking_price: PositiveMoney | None = None
    min_price: PositiveMoney | None = None
    notes: NoteText | None = None


class VehicleIn(_VehicleFields):
    make: NameText
    model: NameText
    acquisition_source: Literal["DIRECT_PURCHASE", "AUCTION", "IMPORT"] = "DIRECT_PURCHASE"
    current_location_id: UUID | None = None


class VehicleUpdate(_VehicleFields):
    pass


class VehicleStatusIn(StrictModel):
    status: VehicleStatus
    reason: NoteText | None = None


class VehicleMoveIn(StrictModel):
    location_id: UUID
    reason: NoteText | None = None


class VehicleRow(BaseModel):
    """One inventory row. Cost fields only with vehicle.view_cost."""

    id: UUID
    stock_no: str
    make: str
    model: str
    trim: str | None
    year: int | None
    color_ext: str | None
    plate_no: str | None
    vin: str | None
    status: VehicleStatus
    ownership_type: Literal["OWNED", "CONSIGNED_IN"]
    location_name_ar: str | None
    location_name_en: str | None
    asking_price: Money | None
    stock_date: date | None
    days_in_stock: int | None
    aging: Aging | None
    photo_url: str | None
    min_price: Money | None = None
    total_cost: Money | None = None
    cost_complete: bool | None = None


class VehiclePage(BaseModel):
    items: list[VehicleRow]
    page: int
    page_size: int
    total: int


class StatusChange(BaseModel):
    from_status: VehicleStatus | None
    to_status: VehicleStatus
    changed_at: datetime
    reason: str | None


class LocationChange(BaseModel):
    from_name_ar: str | None
    to_name_ar: str | None
    moved_at: datetime
    reason: str | None


class PriceChange(BaseModel):
    asking_price: Money | None
    changed_at: datetime
    min_price: Money | None = None


class MediaOut(BaseModel):
    id: UUID
    url: str | None
    sort_order: int


class DocumentOut(BaseModel):
    id: UUID
    entity_type: DocumentEntity
    entity_id: UUID
    doc_type: DocumentType
    file_name: str
    content_type: str
    size_bytes: int
    sensitivity: Literal["NORMAL", "COST"]
    created_at: datetime


class ActiveReservation(BaseModel):
    id: UUID
    customer_id: UUID
    customer_name: str
    deposit_amount: Money
    reservation_date: date
    expires_on: date | None
    expired: bool


class VehicleSaleInfo(BaseModel):
    id: UUID
    sale_no: str
    sale_date: date
    buyer_customer_id: UUID | None
    # For an external-showroom sale: the showroom that sold it.
    buyer_name: str
    sale_price: Money
    invoice_no: str | None
    channel: Literal["DIRECT", "EXTERNAL_SHOWROOM"] = "DIRECT"


class VehicleConsignment(BaseModel):
    """A consigned-in car's agreement (SPEC §4.4)."""

    id: UUID
    consignor_id: UUID
    consignor_name: str
    status: Literal["ACTIVE", "SOLD", "RETURNED"]
    end_date: date | None


class VehicleConsignedOut(BaseModel):
    """Our car at another showroom (SPEC §4.5)."""

    id: UUID
    external_showroom_id: UUID
    external_showroom_name: str
    sent_date: date
    commission_type: Literal["FIXED", "PCT"]
    commission_value: Decimal
    expected_price: Money | None


class CostLine(BaseModel):
    entry_date: date
    entry_no: int
    source_type: str
    label: str
    amount: Money
    reversed: bool
    is_reversal: bool


class PurchaseSummary(BaseModel):
    id: UUID
    # OPENING: brought in by the Excel import at go-live (D-108).
    source: Literal["PURCHASE", "TRADE_IN", "OPENING"]
    seller_customer_id: UUID | None
    seller_name: str | None
    purchase_date: date
    price: Money
    deferred_amount: Money
    outstanding: Money
    entry_no: int


class VehicleProfit(BaseModel):
    # CONSIGNMENT: sale_price is the commission earned and cost what the showroom bore (P-05).
    kind: Literal["SALE", "CONSIGNMENT"] = "SALE"
    sale_price: Money
    cost: Money
    # Kept by an external showroom that sold the car; profit is after it (Q-34).
    external_commission: Money = Decimal(0)
    gross_profit: Money
    profit_pct: Decimal
    # True while expected cost categories are missing: shown as an estimate.
    estimate: bool


class VehicleCost(BaseModel):
    total_cost: Money
    lines: list[CostLine]
    cost_complete: bool
    missing_categories: list[str]


class VehicleDetail(BaseModel):
    id: UUID
    stock_no: str
    vin: str | None
    plate_no: str | None
    make: str
    model: str
    trim: str | None
    year: int | None
    color_ext: str | None
    color_int: str | None
    body_type: str | None
    transmission: Transmission | None
    fuel: Fuel | None
    engine_cc: int | None
    mileage_km: int | None
    license_expiry: date | None
    license_governorate: str | None
    ownership_type: Literal["OWNED", "CONSIGNED_IN"]
    acquisition_source: AcquisitionSource
    status: VehicleStatus
    current_location_id: UUID | None
    location_name_ar: str | None
    location_name_en: str | None
    asking_price: Money | None
    stock_date: date | None
    days_in_stock: int | None
    aging: Aging | None
    days_since_price_change: int | None
    notes: str | None
    archived: bool
    status_history: list[StatusChange]
    location_history: list[LocationChange]
    price_history: list[PriceChange]
    media: list[MediaOut]
    documents: list[DocumentOut]
    reservation: ActiveReservation | None
    sale: VehicleSaleInfo | None
    consignment: "VehicleConsignment | None" = None
    consigned_out: "VehicleConsignedOut | None" = None
    min_price: Money | None = None
    purchase: PurchaseSummary | None = None
    cost: VehicleCost | None = None
    profit: VehicleProfit | None = None


class VehicleHit(BaseModel):
    id: UUID
    stock_no: str
    label: str
    plate_no: str | None
    vin: str | None
    status: VehicleStatus


class CustomerHit(BaseModel):
    id: UUID
    name: str
    phone_primary: str | None


class SearchOut(BaseModel):
    vehicles: list[VehicleHit]
    customers: list[CustomerHit]


# --- Purchase (rules 6, 7, 8) -------------------------------------------------------------------


class CashLegIn(StrictModel):
    cash_account_id: UUID
    amount: PositiveMoney


class PurchaseIn(StrictModel):
    seller_customer_id: UUID
    purchase_date: date
    price: PositiveMoney
    payments: list[CashLegIn] = Field(default_factory=list, max_length=5)
    notes: NoteText | None = None
    # Skip "in preparation" when the car is ready for sale straight away.
    ready_for_sale: bool = False


class PurchaseOut(BaseModel):
    id: UUID
    vehicle_id: UUID
    seller_customer_id: UUID
    seller_name: str
    purchase_date: date
    price: Money
    deferred_amount: Money
    status: Literal["POSTED", "REVERSED"]
    entry_no: int


class SellerPaymentIn(StrictModel):
    payment_date: date
    amount: PositiveMoney
    cash_account_id: UUID
    notes: NoteText | None = None


class SellerPaymentOut(BaseModel):
    id: UUID
    vehicle_id: UUID
    payment_date: date
    amount: Money
    cash_account_id: UUID
    status: Literal["POSTED", "REVERSED"]
    entry_no: int


# --- Vehicle expenses (rules 9, 30, 31; P-04) -----------------------------------------------------


class VehicleExpenseIn(StrictModel):
    expense_date: date
    category_id: UUID
    amount: PositiveMoney
    funding: FundingKind = "CASH_ACCOUNT"
    cash_account_id: UUID | None = None
    supplier_id: UUID | None = None
    paid_by_partner_id: UUID | None = None
    partner_funding_mode: PartnerFundingMode | None = None
    description: NoteText | None = None

    @model_validator(mode="after")
    def _one_funding_source(self) -> "VehicleExpenseIn":
        given = {
            "CASH_ACCOUNT": self.cash_account_id is not None,
            "SUPPLIER_CREDIT": self.supplier_id is not None,
            "PARTNER": self.paid_by_partner_id is not None or self.partner_funding_mode is not None,
        }
        partner_complete = self.paid_by_partner_id is not None and self.partner_funding_mode is not None
        if [kind for kind, present in given.items() if present] != [self.funding] or (
            self.funding == "PARTNER" and not partner_complete
        ):
            raise ValueError("give exactly the details of the chosen funding")
        return self


class VehicleExpenseOut(BaseModel):
    id: UUID
    vehicle_id: UUID
    expense_date: date
    category_id: UUID
    category_code: str
    category_name_ar: str
    category_name_en: str
    amount: Money
    description: str | None
    funding: FundingKind
    cash_account_name_ar: str | None
    supplier_name: str | None
    paid_by_partner_name_ar: str | None
    treatment: Literal["CAPITALIZE", "COGS", "RECOVERABLE", "SHOWROOM", "SHARED"]
    status: Literal["POSTED", "REVERSED"]
    entry_no: int


# --- Uploads (D-15, D-74) ------------------------------------------------------------------------


class MediaUploadIn(StrictModel):
    content_type: ImageType
    size_bytes: int = Field(gt=0, le=5 * 1024 * 1024)


class UploadTicket(BaseModel):
    """PUT the file to upload_url (valid 15 minutes), then register storage_path."""

    upload_url: str
    storage_path: str


class MediaRegisterIn(StrictModel):
    storage_path: Annotated[str, StringConstraints(max_length=300)]
    content_type: ImageType
    size_bytes: int = Field(gt=0, le=5 * 1024 * 1024)


class DocumentUploadIn(StrictModel):
    entity_type: DocumentEntity
    entity_id: UUID
    doc_type: DocumentType
    file_name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
    content_type: DocumentContentType
    size_bytes: int = Field(gt=0, le=10 * 1024 * 1024)


class DocumentRegisterIn(DocumentUploadIn):
    storage_path: Annotated[str, StringConstraints(max_length=300)]


class SignedUrlOut(BaseModel):
    url: str
