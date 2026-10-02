"""Request and response models for session, tenant and user management."""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, EmailStr, Field, StringConstraints, field_validator

NonEmptyText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
OptionalText = Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)]
PhoneText = Annotated[str, StringConstraints(strip_whitespace=True, pattern=r"^\+?[0-9 ]{6,20}$")]

Language = Literal["ar", "en"]
DigitStyle = Literal["WESTERN", "ARABIC_INDIC"]
# Roles a tenant user can be given. Custom roles come later (A-02).
AssignableRole = Literal["OWNER", "MANAGER", "ACCOUNTANT", "SALES", "PARTNER", "VIEWER"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


# --- /me ------------------------------------------------------------------------


class UserOut(BaseModel):
    id: UUID
    email: str | None
    full_name: str | None


class MembershipOut(BaseModel):
    tenant_id: UUID
    tenant_name_ar: str
    tenant_name_en: str | None
    country_code: str
    currency_code: str
    timezone: str
    role_code: str
    partner_id: UUID | None
    subscription_status: str
    permissions: list[str]
    feature_flags: dict[str, bool]


class MeOut(BaseModel):
    user: UserOut
    is_platform_admin: bool
    memberships: list[MembershipOut]


# --- /tenant --------------------------------------------------------------------


class TenantProfileOut(BaseModel):
    id: UUID
    name_ar: str
    name_en: str | None
    country_code: str
    currency_code: str
    timezone: str
    commercial_reg_no: str | None
    tax_reg_no: str | None
    address: str | None
    phones: list[str]
    logo_path: str | None


class TenantSettingsOut(BaseModel):
    fiscal_year_start_month: int
    default_language: Language
    digit_style: DigitStyle
    cash_negative_policy: Literal["WARN", "BLOCK"]
    aging_thresholds: list[int]
    expected_cost_categories: list[str]
    partner_sees_summary: bool
    installment_markup_mode: Literal["A", "B_ENABLED"]
    profit_policy: Literal["PERIODIC", "PER_CAR"]
    distribution_frequency: Literal["AD_HOC", "MONTHLY", "QUARTERLY", "YEARLY"]
    loss_handling: Literal["ALLOCATE_TO_PARTNERS", "CARRY_FORWARD"]
    prorata_method: Literal["DAY_WEIGHTED", "SUB_PERIOD_PROFIT"]
    rounding_remainder: Literal["LARGEST_REMAINDER", "LARGEST_SHARE"]
    sale_cancellation_method: Literal["REFUND_LIABILITY", "MIRROR"]
    overpayment_policy: Literal["BLOCK", "ALLOW_AS_CREDIT"]


class TenantOut(BaseModel):
    profile: TenantProfileOut
    settings: TenantSettingsOut


class TenantProfileUpdate(StrictModel):
    name_ar: NonEmptyText | None = None
    name_en: OptionalText | None = None
    commercial_reg_no: OptionalText | None = None
    tax_reg_no: OptionalText | None = None
    address: OptionalText | None = None
    phones: list[PhoneText] | None = Field(default=None, max_length=5)
    timezone: str | None = None

    @field_validator("timezone")
    @classmethod
    def _known_timezone(cls, value: str | None) -> str | None:
        if value is None:
            return value
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError("unknown timezone") from exc
        return value


class TenantSettingsUpdate(StrictModel):
    fiscal_year_start_month: int | None = Field(default=None, ge=1, le=12)
    default_language: Language | None = None
    digit_style: DigitStyle | None = None
    cash_negative_policy: Literal["WARN", "BLOCK"] | None = None
    aging_thresholds: list[int] | None = Field(default=None, min_length=3, max_length=3)
    expected_cost_categories: list[NonEmptyText] | None = Field(default=None, max_length=30)
    partner_sees_summary: bool | None = None
    installment_markup_mode: Literal["A", "B_ENABLED"] | None = None
    profit_policy: Literal["PERIODIC", "PER_CAR"] | None = None
    distribution_frequency: Literal["AD_HOC", "MONTHLY", "QUARTERLY", "YEARLY"] | None = None
    loss_handling: Literal["ALLOCATE_TO_PARTNERS", "CARRY_FORWARD"] | None = None
    prorata_method: Literal["DAY_WEIGHTED", "SUB_PERIOD_PROFIT"] | None = None
    rounding_remainder: Literal["LARGEST_REMAINDER", "LARGEST_SHARE"] | None = None
    sale_cancellation_method: Literal["REFUND_LIABILITY", "MIRROR"] | None = None
    overpayment_policy: Literal["BLOCK", "ALLOW_AS_CREDIT"] | None = None

    @field_validator("aging_thresholds")
    @classmethod
    def _ascending(cls, value: list[int] | None) -> list[int] | None:
        if value is not None and not (0 < value[0] < value[1] < value[2] <= 3650):
            raise ValueError("thresholds must be three ascending positive day counts")
        return value


# --- /users ---------------------------------------------------------------------


class MemberOut(BaseModel):
    membership_id: UUID
    user_id: UUID
    email: str | None
    full_name: str | None
    role_code: str
    status: Literal["ACTIVE", "DISABLED"]
    partner_id: UUID | None
    last_sign_in_at: datetime | None
    created_at: datetime


class InviteIn(StrictModel):
    email: EmailStr
    full_name: OptionalText | None = None
    role_code: AssignableRole


class MemberUpdate(StrictModel):
    role_code: AssignableRole | None = None
    status: Literal["ACTIVE", "DISABLED"] | None = None
    # Link the user to a partner record (a partner sees their own statement); null unlinks.
    partner_id: UUID | None = None


class RoleOut(BaseModel):
    code: str
    name_ar: str
    name_en: str
