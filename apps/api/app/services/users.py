"""Tenant user management: list, invite, change role or status (BACKLOG 1.9).

Business rule: a tenant always keeps at least one active OWNER, so nobody can
lock the showroom out of its own settings.
"""

from uuid import UUID

from sqlalchemy import Connection, text
from sqlalchemy.exc import IntegrityError

from app.core.errors import AppError, not_found
from app.domain.tenancy import InviteIn, MemberOut, MemberUpdate, RoleOut
from app.integrations.supabase_auth_admin import AuthAdmin
from app.services import plans
from app.services.audit import record_event

_MEMBERS = text("select * from private.tenant_members()")
_ROLES = text(
    """
    select code, name_ar, name_en from public.roles
     where tenant_id is null or tenant_id = private.current_tenant_id()
     order by sort_order, code
    """
)
_ROLE_ID = text(
    """
    select id from public.roles
     where code = :code and (tenant_id is null or tenant_id = private.current_tenant_id())
     order by tenant_id nulls last
     limit 1
    """
)
_FIND_USER = text("select private.find_user_id_by_email(:email)")
_INSERT_MEMBERSHIP = text(
    """
    insert into public.memberships (tenant_id, user_id, role_id, invited_by)
    values (:tenant_id, :user_id, :role_id, :invited_by)
    returning id
    """
)
_ACTIVE_OWNERS_EXCEPT = text(
    """
    select count(*) from public.memberships m
      join public.roles r on r.id = m.role_id
     where m.tenant_id = :tenant_id and m.status = 'ACTIVE' and r.code = 'OWNER' and m.id <> :membership_id
    """
)
_MEMBERSHIP_FOR_UPDATE = text(
    """
    select m.id, r.code as role_code, m.status from public.memberships m
      join public.roles r on r.id = m.role_id
     where m.id = :membership_id and m.tenant_id = :tenant_id
     for update of m
    """
)


def list_members(conn: Connection) -> list[MemberOut]:
    return [MemberOut.model_validate(dict(row)) for row in conn.execute(_MEMBERS).mappings()]


def list_roles(conn: Connection) -> list[RoleOut]:
    return [RoleOut.model_validate(dict(row)) for row in conn.execute(_ROLES).mappings()]


def _role_id(conn: Connection, code: str) -> UUID:
    role_id = conn.execute(_ROLE_ID, {"code": code}).scalar_one_or_none()
    if role_id is None:
        raise not_found("role")
    return UUID(str(role_id))


def find_existing_user(conn: Connection, email: str) -> UUID | None:
    user_id = conn.execute(_FIND_USER, {"email": email}).scalar_one_or_none()
    return UUID(str(user_id)) if user_id else None


def invite(
    conn: Connection,
    *,
    tenant_id: UUID,
    actor: UUID,
    payload: InviteIn,
    auth_admin: AuthAdmin,
    redirect_to: str,
) -> MemberOut:
    """Add a member. An existing account (e.g. a partner in another showroom)
    just gets a membership; a new email gets an account and an invitation email.

    The Auth call happens before the membership insert and cannot be rolled
    back; a failed insert leaves an account without any tenant, which grants
    no access.
    """
    role_id = _role_id(conn, payload.role_code)
    user_id = find_existing_user(conn, str(payload.email))
    if (
        user_id is not None
        and conn.execute(
            text("select 1 from public.memberships where tenant_id = :t and user_id = :u"),
            {"t": tenant_id, "u": user_id},
        ).first()
    ):
        raise AppError("MEMBER_ALREADY_EXISTS", "This user is already a member of the showroom", status_code=409)
    plans.ensure_room(conn, "users")
    is_new_account = user_id is None
    if user_id is None:
        user_id = auth_admin.invite_user(email=str(payload.email), full_name=payload.full_name, redirect_to=redirect_to)

    try:
        with conn.begin_nested():
            membership_id = conn.execute(
                _INSERT_MEMBERSHIP,
                {"tenant_id": tenant_id, "user_id": user_id, "role_id": role_id, "invited_by": actor},
            ).scalar_one()
    except IntegrityError as exc:
        raise AppError(
            "MEMBER_ALREADY_EXISTS", "This user is already a member of the showroom", status_code=409
        ) from exc

    record_event(
        conn,
        tenant_id=tenant_id,
        actor=actor,
        action="USER_INVITED",
        entity_type="memberships",
        entity_id=str(membership_id),
        details={"email": str(payload.email), "role_code": payload.role_code, "new_account": is_new_account},
    )
    return next(m for m in list_members(conn) if m.membership_id == membership_id)


def update_member(
    conn: Connection, *, tenant_id: UUID, actor: UUID, membership_id: UUID, changes: MemberUpdate
) -> MemberOut:
    current = (
        conn.execute(_MEMBERSHIP_FOR_UPDATE, {"membership_id": membership_id, "tenant_id": tenant_id})
        .mappings()
        .first()
    )
    if current is None:
        raise not_found("membership")

    loses_owner = (
        current["role_code"] == "OWNER"
        and current["status"] == "ACTIVE"
        and ((changes.role_code is not None and changes.role_code != "OWNER") or changes.status == "DISABLED")
    )
    if loses_owner:
        others = conn.execute(
            _ACTIVE_OWNERS_EXCEPT, {"tenant_id": tenant_id, "membership_id": membership_id}
        ).scalar_one()
        if others == 0:
            raise AppError("LAST_OWNER", "The showroom must keep at least one active owner", status_code=409)

    values: dict[str, object] = {}
    if changes.role_code is not None:
        values["role_id"] = _role_id(conn, changes.role_code)
    if changes.status is not None:
        if changes.status == "ACTIVE" and current["status"] != "ACTIVE":
            plans.ensure_room(conn, "users")
        values["status"] = changes.status
    if "partner_id" in changes.model_fields_set:
        if changes.partner_id is not None:
            exists = conn.execute(
                text("select 1 from public.partners where id = :id and archived_at is null"),
                {"id": changes.partner_id},
            ).first()
            if exists is None:
                raise AppError("PARTNER_INVALID", "Unknown or archived partner", status_code=422)
        values["partner_id"] = changes.partner_id
    if values:
        assignments = ", ".join(f"{column} = :{column}" for column in values)
        try:
            with conn.begin_nested():
                conn.execute(
                    text(f"update public.memberships set {assignments} where id = :membership_id"),  # noqa: S608
                    {**values, "membership_id": membership_id},
                )
        except IntegrityError as exc:
            raise AppError(
                "PARTNER_ALREADY_LINKED", "This partner is already linked to another user", status_code=409
            ) from exc
        record_event(
            conn,
            tenant_id=tenant_id,
            actor=actor,
            action="MEMBERSHIP_CHANGED",
            entity_type="memberships",
            entity_id=str(membership_id),
            details=changes.model_dump(mode="json", exclude_unset=True),
        )
    return next(m for m in list_members(conn) if m.membership_id == membership_id)
