-- =============================================================================
-- Access control: permission resolution, RLS helper functions, policies.
-- Design: docs/ARCHITECTURE.md §4 (helpers and policy patterns), D-10.
--
-- Policy idiom: tenant_id = any ((select private.tenants_with_permission('x'))::uuid[])
-- The sub-select makes Postgres evaluate the helper once per statement rather
-- than once per row.
-- =============================================================================

-- -----------------------------------------------------------------------------
-- Permission resolution: role bundle, minus revoked overrides, plus granted
-- overrides. Only for ACTIVE memberships of ACTIVE tenants. Single source of
-- truth for both RLS and the API.
-- -----------------------------------------------------------------------------
create or replace function private.effective_permissions(p_tenant uuid, p_user uuid)
returns text[]
language sql
stable
security definer
set search_path = ''
as $$
  with m as (
    select m.role_id
    from public.memberships m
    join public.tenants t on t.id = m.tenant_id
    where m.tenant_id = p_tenant
      and m.user_id = p_user
      and m.status = 'ACTIVE'
      and t.status = 'ACTIVE'
  ),
  overrides as (
    select o.permission_code, o.granted
    from public.tenant_role_permission_overrides o
    join m on m.role_id = o.role_id
    where o.tenant_id = p_tenant
  ),
  codes as (
    select rp.permission_code as code
    from public.role_permissions rp
    join m on m.role_id = rp.role_id
    where rp.permission_code not in (select permission_code from overrides where not granted)
    union
    select permission_code from overrides where granted
  )
  select coalesce(array_agg(code order by code), '{}') from codes;
$$;

-- Tenants where a user holds an active membership.
create or replace function private.user_tenant_ids(p_user uuid)
returns uuid[]
language sql
stable
security definer
set search_path = ''
as $$
  select coalesce(array_agg(m.tenant_id), '{}')
  from public.memberships m
  join public.tenants t on t.id = m.tenant_id
  where m.user_id = p_user and m.status = 'ACTIVE' and t.status = 'ACTIVE';
$$;

-- --- Browser-side helpers (auth.uid()) ----------------------------------------
create or replace function private.my_tenant_ids()
returns uuid[]
language sql
stable
security definer
set search_path = ''
as $$
  select private.user_tenant_ids((select auth.uid()));
$$;

create or replace function private.tenants_with_permission(p_perm text)
returns uuid[]
language sql
stable
security definer
set search_path = ''
as $$
  select coalesce(array_agg(t.tenant_id), '{}')
  from unnest(private.my_tenant_ids()) as t (tenant_id)
  where p_perm = any (private.effective_permissions(t.tenant_id, (select auth.uid())));
$$;

create or replace function private.is_member(p_tenant uuid)
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
  select p_tenant = any (private.my_tenant_ids());
$$;

create or replace function private.has_permission(p_tenant uuid, p_perm text)
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
  select p_perm = any (private.effective_permissions(p_tenant, (select auth.uid())));
$$;

create or replace function private.has_any_permission(p_tenant uuid, p_perms text[])
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
  select private.effective_permissions(p_tenant, (select auth.uid())) && p_perms;
$$;

create or replace function private.my_partner_id(p_tenant uuid)
returns uuid
language sql
stable
security definer
set search_path = ''
as $$
  select m.partner_id
  from public.memberships m
  where m.tenant_id = p_tenant and m.user_id = (select auth.uid()) and m.status = 'ACTIVE';
$$;

create or replace function private.is_platform_admin()
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
  select exists (select 1 from public.platform_admins where user_id = (select auth.uid()));
$$;

-- False when the tenant is archived or its subscription is suspended: the
-- tenant becomes read-only (SPEC §4.16). Used in every browser write policy.
create or replace function private.tenant_writable(p_tenant uuid)
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
  select exists (
    select 1
    from public.tenants t
    left join public.subscriptions s on s.tenant_id = t.id
    where t.id = p_tenant
      and t.status = 'ACTIVE'
      and coalesce(s.status, 'ACTIVE') <> 'SUSPENDED'
  );
$$;

-- Tenant override first, then the plan default, else off.
create or replace function private.feature_enabled(p_tenant uuid, p_flag text)
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
  select coalesce(
    (select f.enabled from public.feature_flags f where f.tenant_id = p_tenant and f.flag_key = p_flag),
    (select f.enabled
       from public.feature_flags f
       join public.subscriptions s on s.plan_id = f.plan_id
      where s.tenant_id = p_tenant and f.flag_key = p_flag),
    false
  );
$$;

-- Browser and API may call the auth.uid()-based helpers; only the API may ask
-- about an arbitrary user. (See the foundation migration for why the revoke.)
revoke execute on all routines in schema private from public, anon, authenticated, service_role;
grant execute on function
  private.current_tenant_id(),
  private.current_user_id(),
  private.current_actor_id()
  to authenticated, app_api;

grant execute on function
  private.my_tenant_ids(),
  private.tenants_with_permission(text),
  private.is_member(uuid),
  private.has_permission(uuid, text),
  private.has_any_permission(uuid, text[]),
  private.my_partner_id(uuid),
  private.is_platform_admin(),
  private.tenant_writable(uuid),
  private.feature_enabled(uuid, text)
  to authenticated, app_api;

grant execute on function
  private.effective_permissions(uuid, uuid),
  private.user_tenant_ids(uuid)
  to app_api;

-- =============================================================================
-- Policies. "authenticated" = browser through PostgREST (auth.uid()).
-- "app_api" = FastAPI, scoped by app.tenant_id / app.user_id.
-- No browser INSERT/UPDATE policies exist yet: every table in this phase is
-- written through the API (D-04).
-- =============================================================================

-- Reference data: readable by every signed-in user and the API.
create policy country_packs_read on public.country_packs
  for select to authenticated, app_api using (true);
create policy permissions_read on public.permissions
  for select to authenticated, app_api using (true);
create policy role_permission_restrictions_read on public.role_permission_restrictions
  for select to authenticated, app_api using (true);
create policy plans_read on public.plans
  for select to authenticated, app_api using (true);

-- tenants ----------------------------------------------------------------------
create policy tenants_member_read on public.tenants
  for select to authenticated
  using (id = any ((select private.my_tenant_ids())::uuid[]));

create policy tenants_api_read on public.tenants
  for select to app_api
  using (
    id = (select private.current_tenant_id())
    or id = any ((select private.user_tenant_ids(private.current_user_id()))::uuid[])
  );

create policy tenants_api_update on public.tenants
  for update to app_api
  using (id = (select private.current_tenant_id()))
  with check (id = (select private.current_tenant_id()));

-- tenant_settings ----------------------------------------------------------------
create policy tenant_settings_member_read on public.tenant_settings
  for select to authenticated
  using (tenant_id = any ((select private.my_tenant_ids())::uuid[]));

create policy tenant_settings_api_read on public.tenant_settings
  for select to app_api
  using (tenant_id = (select private.current_tenant_id()));

create policy tenant_settings_api_update on public.tenant_settings
  for update to app_api
  using (tenant_id = (select private.current_tenant_id()))
  with check (tenant_id = (select private.current_tenant_id()));

-- branches ---------------------------------------------------------------------
create policy branches_member_read on public.branches
  for select to authenticated
  using (tenant_id = any ((select private.my_tenant_ids())::uuid[]));

create policy branches_api_all on public.branches
  for all to app_api
  using (tenant_id = (select private.current_tenant_id()))
  with check (tenant_id = (select private.current_tenant_id()));

-- roles and permissions --------------------------------------------------------
create policy roles_member_read on public.roles
  for select to authenticated
  using (tenant_id is null or tenant_id = any ((select private.my_tenant_ids())::uuid[]));

create policy roles_api_read on public.roles
  for select to app_api
  using (
    tenant_id is null
    or tenant_id = (select private.current_tenant_id())
    or tenant_id = any ((select private.user_tenant_ids(private.current_user_id()))::uuid[])
  );

-- The roles policy above applies inside the EXISTS, so only visible roles count.
create policy role_permissions_read on public.role_permissions
  for select to authenticated, app_api
  using (exists (select 1 from public.roles r where r.id = role_id));

create policy role_overrides_member_read on public.tenant_role_permission_overrides
  for select to authenticated
  using (tenant_id = any ((select private.my_tenant_ids())::uuid[]));

create policy role_overrides_api_all on public.tenant_role_permission_overrides
  for all to app_api
  using (tenant_id = (select private.current_tenant_id()))
  with check (tenant_id = (select private.current_tenant_id()));

-- memberships ------------------------------------------------------------------
-- A user sees their own memberships; user managers see the whole tenant.
create policy memberships_read on public.memberships
  for select to authenticated
  using (
    user_id = (select auth.uid())
    or tenant_id = any ((select private.tenants_with_permission('users.manage'))::uuid[])
  );

create policy memberships_api_read on public.memberships
  for select to app_api
  using (
    tenant_id = (select private.current_tenant_id())
    or user_id = (select private.current_user_id())
  );

create policy memberships_api_insert on public.memberships
  for insert to app_api
  with check (tenant_id = (select private.current_tenant_id()));

create policy memberships_api_update on public.memberships
  for update to app_api
  using (tenant_id = (select private.current_tenant_id()))
  with check (tenant_id = (select private.current_tenant_id()));

-- tenant_counters: API only ------------------------------------------------------
create policy tenant_counters_api_all on public.tenant_counters
  for all to app_api
  using (tenant_id = (select private.current_tenant_id()))
  with check (tenant_id = (select private.current_tenant_id()));

-- platform_admins: a user can see whether they are one ---------------------------
create policy platform_admins_self_read on public.platform_admins
  for select to authenticated
  using (user_id = (select auth.uid()));

create policy platform_admins_api_read on public.platform_admins
  for select to app_api
  using (user_id = (select private.current_user_id()));

-- subscriptions ----------------------------------------------------------------
create policy subscriptions_member_read on public.subscriptions
  for select to authenticated
  using (tenant_id = any ((select private.my_tenant_ids())::uuid[]));

create policy subscriptions_api_read on public.subscriptions
  for select to app_api
  using (
    tenant_id = (select private.current_tenant_id())
    or tenant_id = any ((select private.user_tenant_ids(private.current_user_id()))::uuid[])
  );

-- feature_flags ----------------------------------------------------------------
create policy feature_flags_member_read on public.feature_flags
  for select to authenticated
  using (tenant_id is null or tenant_id = any ((select private.my_tenant_ids())::uuid[]));

create policy feature_flags_api_read on public.feature_flags
  for select to app_api
  using (
    tenant_id is null
    or tenant_id = (select private.current_tenant_id())
    or tenant_id = any ((select private.user_tenant_ids(private.current_user_id()))::uuid[])
  );

-- audit_log ----------------------------------------------------------------------
create policy audit_log_read on public.audit_log
  for select to authenticated
  using (tenant_id = any ((select private.tenants_with_permission('audit.view'))::uuid[]));

create policy audit_log_api_read on public.audit_log
  for select to app_api
  using (tenant_id = (select private.current_tenant_id()));

-- Tenant-less events (e.g. login before a tenant is chosen) are allowed.
create policy audit_log_api_insert on public.audit_log
  for insert to app_api
  with check (tenant_id is null or tenant_id = (select private.current_tenant_id()));
