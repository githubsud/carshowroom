"""Session bootstrap, tenant profile/settings and user management (docs/API.md §3.1)."""

from uuid import UUID

from fastapi import APIRouter, Depends, Request

from app.api.deps import TenantContext, get_current_user, get_database, require, require_writable
from app.core.config import get_settings
from app.core.security import AuthenticatedUser
from app.db.session import Database
from app.domain.permissions import Permission
from app.domain.tenancy import (
    InviteIn,
    MemberOut,
    MemberUpdate,
    MeOut,
    RoleOut,
    TenantOut,
    TenantProfileUpdate,
    TenantSettingsUpdate,
)
from app.integrations.supabase_auth_admin import AuthAdmin
from app.services import tenancy, users

router = APIRouter()


def get_auth_admin(request: Request) -> AuthAdmin:
    admin: AuthAdmin = request.app.state.auth_admin
    return admin


@router.get("/me", response_model=MeOut, tags=["session"])
def me(user: AuthenticatedUser = Depends(get_current_user), db: Database = Depends(get_database)) -> MeOut:
    """The signed-in user and every active showroom membership with its permissions."""
    with db.transaction(user_id=user.id) as conn:
        return tenancy.load_me(conn, user)


# Any active member may read the profile and settings of their tenant.
@router.get("/tenant", response_model=TenantOut, tags=["tenant"])
def get_tenant(
    ctx: TenantContext = Depends(require()),
    db: Database = Depends(get_database),
) -> TenantOut:
    with db.transaction(user_id=ctx.user.id, tenant_id=ctx.tenant_id) as conn:
        return tenancy.load_tenant(conn, ctx.tenant_id)


@router.patch("/tenant/profile", response_model=TenantOut, tags=["tenant"])
def update_profile(
    payload: TenantProfileUpdate,
    ctx: TenantContext = Depends(require(Permission.TENANT_SETTINGS_MANAGE)),
    db: Database = Depends(get_database),
) -> TenantOut:
    require_writable(ctx)
    with db.transaction(user_id=ctx.user.id, tenant_id=ctx.tenant_id) as conn:
        return tenancy.update_profile(conn, ctx.tenant_id, payload)


@router.patch("/tenant/settings", response_model=TenantOut, tags=["tenant"])
def update_settings(
    payload: TenantSettingsUpdate,
    ctx: TenantContext = Depends(require(Permission.TENANT_SETTINGS_MANAGE)),
    db: Database = Depends(get_database),
) -> TenantOut:
    require_writable(ctx)
    with db.transaction(user_id=ctx.user.id, tenant_id=ctx.tenant_id) as conn:
        return tenancy.update_settings(conn, ctx.tenant_id, payload)


@router.get("/roles", response_model=list[RoleOut], tags=["users"])
def list_roles(
    ctx: TenantContext = Depends(require(Permission.USERS_MANAGE)),
    db: Database = Depends(get_database),
) -> list[RoleOut]:
    with db.transaction(user_id=ctx.user.id, tenant_id=ctx.tenant_id) as conn:
        return users.list_roles(conn)


@router.get("/users", response_model=list[MemberOut], tags=["users"])
def list_users(
    ctx: TenantContext = Depends(require(Permission.USERS_MANAGE)),
    db: Database = Depends(get_database),
) -> list[MemberOut]:
    with db.transaction(user_id=ctx.user.id, tenant_id=ctx.tenant_id) as conn:
        return users.list_members(conn)


@router.post("/users/invite", response_model=MemberOut, status_code=201, tags=["users"])
def invite_user(
    payload: InviteIn,
    ctx: TenantContext = Depends(require(Permission.USERS_MANAGE)),
    db: Database = Depends(get_database),
    auth_admin: AuthAdmin = Depends(get_auth_admin),
) -> MemberOut:
    require_writable(ctx)
    with db.transaction(user_id=ctx.user.id, tenant_id=ctx.tenant_id) as conn:
        return users.invite(
            conn,
            tenant_id=ctx.tenant_id,
            actor=ctx.user.id,
            payload=payload,
            auth_admin=auth_admin,
            redirect_to=get_settings().invite_redirect_url,
        )


@router.patch("/users/{membership_id}", response_model=MemberOut, tags=["users"])
def update_user(
    membership_id: UUID,
    payload: MemberUpdate,
    ctx: TenantContext = Depends(require(Permission.USERS_MANAGE)),
    db: Database = Depends(get_database),
) -> MemberOut:
    require_writable(ctx)
    with db.transaction(user_id=ctx.user.id, tenant_id=ctx.tenant_id) as conn:
        return users.update_member(
            conn, tenant_id=ctx.tenant_id, actor=ctx.user.id, membership_id=membership_id, changes=payload
        )
