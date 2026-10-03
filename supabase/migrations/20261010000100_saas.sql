-- =============================================================================
-- Phase 9: SaaS layer and hardening (SPEC §4.16, BACKLOG 9.x).
-- * A suspended or archived tenant is read-only in the database too: every
--   write to its business tables is refused (SR040), whatever the API does.
-- * Tenant-granted, time-boxed support access; manual invoices; self-serve
--   signup; data-driven country terminology.
-- Design: DECISIONS D-113..D-122.
-- =============================================================================

-- -----------------------------------------------------------------------------
-- Read-only tenants (9.2): one guard on every table that holds tenant data.
-- -----------------------------------------------------------------------------
create or replace function private.require_tenant_writable()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_tenant uuid := case when tg_op = 'DELETE' then old.tenant_id else new.tenant_id end;
begin
  if v_tenant is not null and not private.tenant_writable(v_tenant) then
    raise exception 'this showroom is read-only' using errcode = 'SR040';
  end if;
  return case when tg_op = 'DELETE' then old else new end;
end;
$$;

do $$
declare
  t text;
begin
  for t in
    select c.table_name
      from information_schema.columns c
      join information_schema.tables tb on tb.table_schema = c.table_schema and tb.table_name = c.table_name
     where c.table_schema = 'public' and c.column_name = 'tenant_id' and tb.table_type = 'BASE TABLE'
       -- Platform-managed or bookkeeping tables stay writable: suspension, billing and support
       -- are changed on them, logins and reminders keep working, and the audit log records.
       and c.table_name not in ('tenants', 'subscriptions', 'feature_flags', 'memberships', 'audit_log',
                                'notifications', 'reminder_jobs', 'idempotency_keys', 'tenant_counters')
  loop
    execute format(
      'create trigger require_tenant_writable before insert or update or delete on public.%I
         for each row execute function private.require_tenant_writable()', t);
  end loop;
end;
$$;

-- -----------------------------------------------------------------------------
-- Support access (9.4): granted by the tenant, time-boxed, read-only, audited.
-- -----------------------------------------------------------------------------
create table public.support_grants (
  id          uuid primary key default gen_random_uuid(),
  tenant_id   uuid not null references public.tenants (id),
  granted_by  uuid not null,
  reason      text not null check (length(btrim(reason)) >= 3),
  starts_at   timestamptz not null default now(),
  expires_at  timestamptz not null,
  revoked_at  timestamptz,
  created_at  timestamptz not null default now(),
  unique (tenant_id, id),
  check (expires_at > starts_at and expires_at <= starts_at + interval '72 hours')
);
create index support_grants_active_idx on public.support_grants (tenant_id, expires_at) where revoked_at is null;

create or replace function private.support_granted(p_tenant uuid)
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
  select exists (
    select 1 from public.support_grants g
     where g.tenant_id = p_tenant and g.revoked_at is null and now() between g.starts_at and g.expires_at
  );
$$;

-- -----------------------------------------------------------------------------
-- Manual billing (9.3): the super admin issues and marks invoices paid; a
-- PaymentGateway adapter replaces this later.
-- -----------------------------------------------------------------------------
create table public.invoices (
  id            uuid primary key default gen_random_uuid(),
  tenant_id     uuid not null references public.tenants (id),
  period_start  date not null,
  period_end    date not null,
  amount        numeric(18, 2) not null check (amount >= 0),
  currency_code text not null check (currency_code ~ '^[A-Z]{3}$'),
  status        text not null default 'ISSUED' check (status in ('ISSUED', 'PAID', 'VOID')),
  paid_at       timestamptz,
  reference     text,
  marked_by     uuid,
  created_at    timestamptz not null default now(),
  unique (tenant_id, id),
  check (period_end >= period_start),
  check ((status = 'PAID') = (paid_at is not null))
);

-- -----------------------------------------------------------------------------
-- Self-serve signup (9.3): a signed-in user creates a showroom on the trial
-- plan and becomes its owner.
-- -----------------------------------------------------------------------------
create or replace function private.create_tenant(p_owner uuid, p_name_ar text, p_name_en text, p_country text)
returns uuid
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_pack public.country_packs;
  v_tenant uuid := gen_random_uuid();
begin
  select * into v_pack from public.country_packs where code = p_country and is_active;
  if v_pack.code is null then
    raise exception 'unknown country' using errcode = '22023';
  end if;
  insert into public.tenants (id, name_ar, name_en, country_code, currency_code, timezone)
  values (v_tenant, btrim(p_name_ar), nullif(btrim(p_name_en), ''), v_pack.code, v_pack.currency_code,
          v_pack.default_timezone);
  insert into public.branches (tenant_id, name_ar, name_en, is_default)
  values (v_tenant, 'المعرض الرئيسي', 'Main yard', true);
  insert into public.subscriptions (tenant_id, plan_id, status, trial_ends_at)
  select v_tenant, p.id, 'TRIAL', now() + interval '30 days' from public.plans p where p.code = 'TRIAL';
  insert into public.memberships (tenant_id, user_id, role_id)
  select v_tenant, p_owner, r.id from public.roles r where r.code = 'OWNER' and r.tenant_id is null;
  return v_tenant;
end;
$$;

-- -----------------------------------------------------------------------------
-- Platform administrators are checked by the API (app_api has no JWT).
-- -----------------------------------------------------------------------------
create or replace function private.user_is_platform_admin(p_user uuid)
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
  select exists (select 1 from public.platform_admins where user_id = p_user);
$$;


-- -----------------------------------------------------------------------------
-- Super admin console (9.3): the API calls these only for platform admins.
-- -----------------------------------------------------------------------------
create or replace function private.platform_tenants()
returns table (
  id uuid, name_ar text, name_en text, country_code text, tenant_status text, created_at timestamptz,
  plan_code text, subscription_status text, trial_ends_at timestamptz, current_period_end timestamptz,
  users bigint, vehicles_in_stock bigint, journal_lines bigint, last_activity timestamptz, support_granted boolean
)
language sql
stable
security definer
set search_path = ''
as $$
  select t.id, t.name_ar, t.name_en, t.country_code, t.status, t.created_at,
         p.code, s.status, s.trial_ends_at, s.current_period_end,
         (select count(*) from public.memberships m where m.tenant_id = t.id and m.status = 'ACTIVE'),
         (select count(*) from public.vehicles v where v.tenant_id = t.id
            and v.status in ('DRAFT', 'IN_PREPARATION', 'AVAILABLE', 'RESERVED', 'AT_OTHER_SHOWROOM')),
         (select count(*) from public.journal_lines l where l.tenant_id = t.id),
         (select max(a.occurred_at) from public.audit_log a where a.tenant_id = t.id),
         private.support_granted(t.id)
    from public.tenants t
    left join public.subscriptions s on s.tenant_id = t.id
    left join public.plans p on p.id = s.plan_id
   order by t.created_at;
$$;

create or replace function private.platform_update_tenant(
  p_tenant uuid, p_subscription_status text, p_plan_code text, p_tenant_status text, p_period_end timestamptz
)
returns void
language plpgsql
security definer
set search_path = ''
as $$
begin
  if p_subscription_status is not null or p_plan_code is not null or p_period_end is not null then
    update public.subscriptions s
       set status = coalesce(p_subscription_status, s.status),
           plan_id = coalesce((select id from public.plans where code = p_plan_code), s.plan_id),
           current_period_end = coalesce(p_period_end, s.current_period_end)
     where s.tenant_id = p_tenant;
  end if;
  if p_tenant_status is not null then
    update public.tenants set status = p_tenant_status where id = p_tenant;
  end if;
end;
$$;

create or replace function private.user_owned_tenants(p_user uuid)
returns setof uuid
language sql
stable
security definer
set search_path = ''
as $$
  select m.tenant_id from public.memberships m join public.roles r on r.id = m.role_id
   where m.user_id = p_user and r.code = 'OWNER';
$$;

-- 2FA (9.8): once a user has a verified TOTP factor, the API wants an aal2 token.
create or replace function private.user_has_mfa(p_user uuid)
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
  select exists (select 1 from auth.mfa_factors f where f.user_id = p_user and f.status = 'verified');
$$;

-- -----------------------------------------------------------------------------
-- Country packs (9.10): terminology variants are data (Q-25).
-- -----------------------------------------------------------------------------
alter table public.country_packs add column terminology jsonb not null default '{}';
update public.country_packs set terminology = '{
  "menu.vehicles": "السيارات",
  "vehicles.title": "السيارات",
  "dashboard.welcome": "أهلاً بك في {{name}}",
  "vehicles.status_AVAILABLE": "متوفرة للبيع"
}' where code = 'QA';

-- -----------------------------------------------------------------------------
-- Performance (9.7): the lists and the dashboard filter on these.
-- -----------------------------------------------------------------------------
create index if not exists vehicles_status_idx on public.vehicles (tenant_id, status, stock_date);
create index if not exists journal_lines_account_date_idx on public.journal_lines (tenant_id, ledger_account_id, entry_date);
create index if not exists sales_status_date_idx on public.sales (tenant_id, status, sale_date);

call private.secure_table('public.support_grants', p_touch => false);
call private.secure_table('public.invoices', p_touch => false);

create policy support_grants_api on public.support_grants for all to app_api using (true) with check (true);
create policy invoices_api on public.invoices for all to app_api using (true) with check (true);
create policy support_grants_read on public.support_grants for select to authenticated
  using (tenant_id = any ((select private.tenants_with_permission('support.grant'))::uuid[]));

revoke execute on all routines in schema private from public, anon, authenticated, service_role;
grant execute on function
  private.current_tenant_id(), private.current_user_id(), private.current_actor_id(),
  private.my_tenant_ids(), private.tenants_with_permission(text), private.is_member(uuid),
  private.has_permission(uuid, text), private.has_any_permission(uuid, text[]),
  private.my_partner_id(uuid), private.is_platform_admin(), private.tenant_writable(uuid),
  private.feature_enabled(uuid, text)
  to authenticated, app_api;
grant execute on function private.active_tenant_ids(), private.paper_transition_allowed(text, text, text),
  private.match_request(uuid), private.support_granted(uuid), private.create_tenant(uuid, text, text, text),
  private.user_is_platform_admin(uuid), private.platform_tenants(),
  private.platform_update_tenant(uuid, text, text, text, timestamptz), private.user_has_mfa(uuid),
  private.user_owned_tenants(uuid)
  to app_api;
