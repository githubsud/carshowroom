"""SaaS layer models (SPEC §4.15, §4.16; BACKLOG 9.x)."""

from datetime import date, datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.domain.money import Money, PositiveMoney
from app.domain.vehicles import NameText, NoteText, ReasonText, StrictModel

SubscriptionStatus = Literal["TRIAL", "ACTIVE", "PAST_DUE", "SUSPENDED"]


# --- Super admin console ------------------------------------------------------------------------------


class PlatformTenant(BaseModel):
    id: UUID
    name_ar: str
    name_en: str | None
    country_code: str
    tenant_status: Literal["ACTIVE", "ARCHIVED"]
    created_at: datetime
    plan_code: str | None
    subscription_status: SubscriptionStatus | None
    trial_ends_at: datetime | None
    current_period_end: datetime | None
    users: int
    vehicles_in_stock: int
    journal_lines: int
    last_activity: datetime | None
    support_granted: bool


class PlatformTenantUpdate(StrictModel):
    subscription_status: SubscriptionStatus | None = None
    plan_code: Literal["TRIAL", "STANDARD"] | None = None
    tenant_status: Literal["ACTIVE", "ARCHIVED"] | None = None
    current_period_end: datetime | None = None
    reason: ReasonText


class InvoiceIn(StrictModel):
    period_start: date
    period_end: date
    amount: Money = Field(ge=0)


class InvoiceOut(BaseModel):
    id: UUID
    tenant_id: UUID
    period_start: date
    period_end: date
    amount: Money
    currency_code: str
    status: Literal["ISSUED", "PAID", "VOID"]
    paid_at: datetime | None
    reference: str | None


class InvoicePaidIn(StrictModel):
    reference: NoteText | None = None


class SupportSummary(BaseModel):
    """What a support engineer sees inside a showroom that granted access: read-only, audited."""

    tenant_id: UUID
    name_ar: str
    subscription_status: str | None
    granted_until: datetime
    counts: dict[str, int]
    vehicles_by_status: dict[str, int]
    recent_events: list[dict[str, Any]]


# --- Tenant side --------------------------------------------------------------------------------------


class SupportGrantIn(StrictModel):
    hours: int = Field(ge=1, le=72)
    reason: ReasonText


class SupportGrantOut(BaseModel):
    id: UUID
    reason: str
    starts_at: datetime
    expires_at: datetime
    revoked_at: datetime | None
    active: bool
    granted_by_name: str | None


class SignupIn(StrictModel):
    name_ar: NameText
    name_en: NameText | None = None
    country_code: Literal["EG", "QA"] = "EG"


class SignupOut(BaseModel):
    tenant_id: UUID


class BranchIn(StrictModel):
    name_ar: NameText
    name_en: NameText | None = None
    address: NoteText | None = None


class BranchOut(BaseModel):
    id: UUID
    name_ar: str
    name_en: str | None
    address: str | None
    is_default: bool


class AuditRow(BaseModel):
    id: int
    occurred_at: datetime
    actor_user_id: UUID | None
    actor_name: str | None
    actor_kind: str
    action: str
    entity_type: str | None
    entity_id: str | None
    before: dict[str, Any] | None
    after: dict[str, Any] | None
    details: dict[str, Any] | None
    ip: str | None


class AuditPage(BaseModel):
    items: list[AuditRow]
    page: int
    page_size: int
    total: int


class UsageOut(BaseModel):
    plan_code: str | None
    limits: dict[str, int]
    used: dict[str, int]


PositiveAmount = PositiveMoney
