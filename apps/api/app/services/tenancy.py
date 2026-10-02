"""Session, tenant profile and settings."""

from typing import Any
from uuid import UUID

from sqlalchemy import Connection, text

from app.core.errors import not_found
from app.core.security import AuthenticatedUser
from app.domain.tenancy import (
    MembershipOut,
    MeOut,
    TenantOut,
    TenantProfileOut,
    TenantProfileUpdate,
    TenantSettingsOut,
    TenantSettingsUpdate,
    UserOut,
)

_MY_MEMBERSHIPS = text(
    """
    select m.tenant_id,
           t.name_ar as tenant_name_ar,
           t.name_en as tenant_name_en,
           t.country_code,
           t.currency_code,
           t.timezone,
           r.code as role_code,
           m.partner_id,
           coalesce(s.status, 'ACTIVE') as subscription_status,
           private.effective_permissions(m.tenant_id, m.user_id) as permissions,
           coalesce(
             (select jsonb_object_agg(k.flag_key, private.feature_enabled(m.tenant_id, k.flag_key))
                from (select distinct flag_key from public.feature_flags) k),
             '{}'::jsonb
           ) as feature_flags
      from public.memberships m
      join public.tenants t on t.id = m.tenant_id
      join public.roles r on r.id = m.role_id
      left join public.subscriptions s on s.tenant_id = m.tenant_id
     where m.user_id = :user_id
       and m.status = 'ACTIVE'
       and t.status = 'ACTIVE'
     order by t.name_ar
    """
)

_IS_PLATFORM_ADMIN = text("select exists (select 1 from public.platform_admins where user_id = :user_id)")

_PROFILE_COLUMNS = list(TenantProfileOut.model_fields)
_SETTINGS_COLUMNS = list(TenantSettingsOut.model_fields)


def load_me(conn: Connection, user: AuthenticatedUser) -> MeOut:
    rows = conn.execute(_MY_MEMBERSHIPS, {"user_id": user.id}).mappings().all()
    metadata = user.claims.get("user_metadata")
    full_name = metadata.get("full_name") if isinstance(metadata, dict) else None
    return MeOut(
        user=UserOut(id=user.id, email=user.email, full_name=full_name),
        is_platform_admin=bool(conn.execute(_IS_PLATFORM_ADMIN, {"user_id": user.id}).scalar_one()),
        memberships=[MembershipOut.model_validate(dict(row)) for row in rows],
    )


def load_tenant(conn: Connection, tenant_id: UUID) -> TenantOut:
    # Column lists come from the response models, never from user input.
    profile = (
        conn.execute(
            text(f"select {', '.join(_PROFILE_COLUMNS)} from public.tenants where id = :id"),  # noqa: S608
            {"id": tenant_id},
        )
        .mappings()
        .first()
    )
    settings = (
        conn.execute(
            text(f"select {', '.join(_SETTINGS_COLUMNS)} from public.tenant_settings where tenant_id = :id"),  # noqa: S608
            {"id": tenant_id},
        )
        .mappings()
        .first()
    )
    if profile is None or settings is None:
        raise not_found("tenant")
    return TenantOut(
        profile=TenantProfileOut.model_validate(dict(profile)),
        settings=TenantSettingsOut.model_validate(dict(settings)),
    )


def _update(conn: Connection, table: str, key_column: str, tenant_id: UUID, values: dict[str, Any]) -> None:
    if not values:
        return
    # Keys are field names of a StrictModel (extra="forbid"), so they are a fixed allowlist.
    assignments = ", ".join(f"{column} = :{column}" for column in values)
    conn.execute(
        text(f"update public.{table} set {assignments} where {key_column} = :tenant_id"),  # noqa: S608
        {**values, "tenant_id": tenant_id},
    )


def update_profile(conn: Connection, tenant_id: UUID, changes: TenantProfileUpdate) -> TenantOut:
    _update(conn, "tenants", "id", tenant_id, changes.model_dump(exclude_unset=True))
    return load_tenant(conn, tenant_id)


def update_settings(conn: Connection, tenant_id: UUID, changes: TenantSettingsUpdate) -> TenantOut:
    _update(conn, "tenant_settings", "tenant_id", tenant_id, changes.model_dump(exclude_unset=True))
    return load_tenant(conn, tenant_id)
