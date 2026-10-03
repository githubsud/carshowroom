"""SaaS layer (docs/API.md §3.13): the super admin console under /admin (no
X-Tenant-Id; platform admins only), and the tenant side — support grants,
signup, branches, plan usage, the audit log and the data export."""

from contextlib import AbstractContextManager
from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from sqlalchemy import Connection

from app.api.deps import TenantContext, get_current_user, get_database, require, require_writable
from app.core.errors import AppError
from app.core.security import AuthenticatedUser
from app.db.session import Database
from app.domain.permissions import Permission
from app.domain.platform import (
    AuditPage,
    BranchIn,
    BranchOut,
    InvoiceIn,
    InvoiceOut,
    InvoicePaidIn,
    PlatformTenant,
    PlatformTenantUpdate,
    SignupIn,
    SignupOut,
    SupportGrantIn,
    SupportGrantOut,
    SupportSummary,
    UsageOut,
)
from app.services import billing, platform

router = APIRouter()


def _tx(db: Database, ctx: TenantContext) -> AbstractContextManager[Connection]:
    return db.transaction(user_id=ctx.user.id, tenant_id=ctx.tenant_id)


def require_platform_admin(
    user: AuthenticatedUser = Depends(get_current_user), db: Database = Depends(get_database)
) -> AuthenticatedUser:
    with db.transaction(user_id=user.id) as conn:
        if not platform.is_platform_admin(conn, user.id):
            raise AppError("PERMISSION_DENIED", "Platform administrators only", status_code=403)
    return user


# --- Super admin console ------------------------------------------------------------------------------


@router.get("/admin/tenants", response_model=list[PlatformTenant], tags=["platform"])
def admin_tenants(
    admin: AuthenticatedUser = Depends(require_platform_admin), db: Database = Depends(get_database)
) -> list[PlatformTenant]:
    with db.transaction(user_id=admin.id) as conn:
        return platform.list_tenants(conn)


@router.patch("/admin/tenants/{tenant_id}", response_model=PlatformTenant, tags=["platform"])
def admin_update_tenant(
    tenant_id: UUID,
    changes: PlatformTenantUpdate,
    admin: AuthenticatedUser = Depends(require_platform_admin),
    db: Database = Depends(get_database),
) -> PlatformTenant:
    with db.transaction(user_id=admin.id, tenant_id=tenant_id) as conn:
        return platform.update_tenant(conn, tenant_id, changes, actor=admin.id)


@router.get("/admin/tenants/{tenant_id}/invoices", response_model=list[InvoiceOut], tags=["platform"])
def admin_invoices(
    tenant_id: UUID, admin: AuthenticatedUser = Depends(require_platform_admin), db: Database = Depends(get_database)
) -> list[InvoiceOut]:
    with db.transaction(user_id=admin.id, tenant_id=tenant_id) as conn:
        return platform.list_invoices(conn, tenant_id)


@router.post("/admin/tenants/{tenant_id}/invoices", response_model=InvoiceOut, status_code=201, tags=["platform"])
def admin_issue_invoice(
    tenant_id: UUID,
    payload: InvoiceIn,
    admin: AuthenticatedUser = Depends(require_platform_admin),
    db: Database = Depends(get_database),
) -> InvoiceOut:
    with db.transaction(user_id=admin.id, tenant_id=tenant_id) as conn:
        return platform.issue_invoice(conn, tenant_id, payload, actor=admin.id)


@router.post("/admin/tenants/{tenant_id}/invoices/{invoice_id}/paid", response_model=InvoiceOut, tags=["platform"])
def admin_mark_paid(
    tenant_id: UUID,
    invoice_id: UUID,
    payload: InvoicePaidIn,
    admin: AuthenticatedUser = Depends(require_platform_admin),
    db: Database = Depends(get_database),
) -> InvoiceOut:
    with db.transaction(user_id=admin.id, tenant_id=tenant_id) as conn:
        return billing.gateway().confirm(conn, invoice_id, payload.reference, actor=admin.id)


@router.get("/admin/tenants/{tenant_id}/support", response_model=SupportSummary, tags=["platform"])
def admin_support_view(
    tenant_id: UUID, admin: AuthenticatedUser = Depends(require_platform_admin), db: Database = Depends(get_database)
) -> SupportSummary:
    with db.transaction(user_id=admin.id, tenant_id=tenant_id) as conn:
        return platform.support_summary(conn, tenant_id, actor=admin.id)


# --- Signup -------------------------------------------------------------------------------------------


@router.post("/signup", response_model=SignupOut, status_code=201, tags=["tenant"])
def signup(
    payload: SignupIn, user: AuthenticatedUser = Depends(get_current_user), db: Database = Depends(get_database)
) -> SignupOut:
    with db.transaction(user_id=user.id) as conn:
        return SignupOut(tenant_id=platform.signup(conn, payload, user_id=user.id))


# --- Tenant side --------------------------------------------------------------------------------------


@router.get("/support-grants", response_model=list[SupportGrantOut], tags=["tenant"])
def support_grants(
    ctx: TenantContext = Depends(require(Permission.SUPPORT_GRANT)), db: Database = Depends(get_database)
) -> list[SupportGrantOut]:
    with _tx(db, ctx) as conn:
        return platform.list_grants(conn)


@router.post("/support-grants", response_model=SupportGrantOut, status_code=201, tags=["tenant"])
def grant_support(
    payload: SupportGrantIn,
    ctx: TenantContext = Depends(require(Permission.SUPPORT_GRANT)),
    db: Database = Depends(get_database),
) -> SupportGrantOut:
    with _tx(db, ctx) as conn:
        return platform.grant_support(conn, payload, actor=ctx.user.id, tenant_id=ctx.tenant_id)


@router.post("/support-grants/{grant_id}/revoke", response_model=SupportGrantOut, tags=["tenant"])
def revoke_support(
    grant_id: UUID,
    ctx: TenantContext = Depends(require(Permission.SUPPORT_GRANT)),
    db: Database = Depends(get_database),
) -> SupportGrantOut:
    with _tx(db, ctx) as conn:
        return platform.revoke_support(conn, grant_id, actor=ctx.user.id, tenant_id=ctx.tenant_id)


@router.get("/branches", response_model=list[BranchOut], tags=["tenant"])
def branches(
    ctx: TenantContext = Depends(require(Permission.DASHBOARD_VIEW)), db: Database = Depends(get_database)
) -> list[BranchOut]:
    with _tx(db, ctx) as conn:
        return platform.list_branches(conn)


@router.post("/branches", response_model=BranchOut, status_code=201, tags=["tenant"])
def create_branch(
    payload: BranchIn,
    ctx: TenantContext = Depends(require(Permission.TENANT_SETTINGS_MANAGE)),
    db: Database = Depends(get_database),
) -> BranchOut:
    require_writable(ctx)
    with _tx(db, ctx) as conn:
        return platform.create_branch(conn, payload)


@router.get("/usage", response_model=UsageOut, tags=["tenant"])
def usage(
    ctx: TenantContext = Depends(require(Permission.TENANT_SETTINGS_MANAGE)), db: Database = Depends(get_database)
) -> UsageOut:
    with _tx(db, ctx) as conn:
        return platform.usage(conn)


@router.get("/audit", response_model=AuditPage, tags=["audit"])
def audit_log(
    entity_type: str | None = None,
    action: str | None = None,
    actor: UUID | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=200)] = 50,
    ctx: TenantContext = Depends(require(Permission.AUDIT_VIEW)),
    db: Database = Depends(get_database),
) -> AuditPage:
    with _tx(db, ctx) as conn:
        return platform.audit_page(
            conn,
            entity_type=entity_type,
            action=action,
            actor=actor,
            date_from=date_from,
            date_to=date_to,
            page=page,
            page_size=page_size,
        )


@router.get(
    "/tenant/export", response_class=Response, responses={200: {"content": {"application/zip": {}}}}, tags=["tenant"]
)
def export(
    ctx: TenantContext = Depends(require(Permission.TENANT_SETTINGS_MANAGE)), db: Database = Depends(get_database)
) -> Response:
    with _tx(db, ctx) as conn:
        content = platform.export_zip(conn, actor=ctx.user.id, tenant_id=ctx.tenant_id)
    return Response(
        content,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="sayyara-export-{ctx.tenant_id}.zip"'},
    )
