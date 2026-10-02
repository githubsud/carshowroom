"""Request dependencies: authentication, tenant context, permission checks.

ARCHITECTURE §4.4: verify the Supabase JWT, resolve the tenant from the
X-Tenant-Id header, verify the membership, load its permissions.
"""

from collections.abc import Callable
from dataclasses import dataclass
from uuid import UUID

from fastapi import Depends, Header, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import text

from app.core.errors import (
    auth_invalid_token,
    permission_denied,
    tenant_access_denied,
    tenant_header_missing,
    tenant_read_only,
)
from app.core.security import AuthenticatedUser, TokenVerifier
from app.db.session import Database
from app.domain.permissions import Permission

_bearer = HTTPBearer(auto_error=False)


def get_database(request: Request) -> Database:
    db: Database = request.app.state.database
    return db


def get_token_verifier(request: Request) -> TokenVerifier:
    verifier: TokenVerifier = request.app.state.token_verifier
    return verifier


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    verifier: TokenVerifier = Depends(get_token_verifier),
) -> AuthenticatedUser:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise auth_invalid_token("Missing bearer token")
    return verifier.verify(credentials.credentials)


@dataclass(frozen=True)
class TenantContext:
    user: AuthenticatedUser
    tenant_id: UUID
    membership_id: UUID
    role_code: str
    partner_id: UUID | None
    permissions: frozenset[str]
    subscription_status: str

    @property
    def writable(self) -> bool:
        return self.subscription_status != "SUSPENDED"

    def can(self, permission: Permission | str) -> bool:
        return str(permission) in self.permissions


_LOAD_MEMBERSHIP = text(
    """
    select m.id as membership_id,
           r.code as role_code,
           m.partner_id,
           coalesce(s.status, 'ACTIVE') as subscription_status,
           private.effective_permissions(m.tenant_id, m.user_id) as permissions
      from public.memberships m
      join public.tenants t on t.id = m.tenant_id
      join public.roles r on r.id = m.role_id
      left join public.subscriptions s on s.tenant_id = m.tenant_id
     where m.tenant_id = :tenant_id
       and m.user_id = :user_id
       and m.status = 'ACTIVE'
       and t.status = 'ACTIVE'
    """
)


def get_tenant_context(
    user: AuthenticatedUser = Depends(get_current_user),
    x_tenant_id: str | None = Header(default=None, alias="X-Tenant-Id"),
    db: Database = Depends(get_database),
) -> TenantContext:
    if not x_tenant_id:
        raise tenant_header_missing()
    try:
        tenant_id = UUID(x_tenant_id)
    except ValueError as exc:
        raise tenant_access_denied() from exc

    with db.transaction(user_id=user.id, tenant_id=tenant_id) as conn:
        row = conn.execute(_LOAD_MEMBERSHIP, {"tenant_id": tenant_id, "user_id": user.id}).mappings().first()
    if row is None:
        raise tenant_access_denied()

    return TenantContext(
        user=user,
        tenant_id=tenant_id,
        membership_id=row["membership_id"],
        role_code=row["role_code"],
        partner_id=row["partner_id"],
        permissions=frozenset(row["permissions"]),
        subscription_status=row["subscription_status"],
    )


def require(*permissions: Permission) -> Callable[[TenantContext], TenantContext]:
    """Dependency factory: the caller must hold every listed permission."""

    def dependency(ctx: TenantContext = Depends(get_tenant_context)) -> TenantContext:
        for permission in permissions:
            if not ctx.can(permission):
                raise permission_denied(str(permission))
        return ctx

    return dependency


def require_writable(ctx: TenantContext) -> None:
    """Call before any write: suspended tenants are read-only (SPEC §4.16)."""
    if not ctx.writable:
        raise tenant_read_only()
