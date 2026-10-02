-- =============================================================================
-- Tenancy, settings, roles and permissions, plans and subscriptions.
-- Design: docs/ERD.md §2, docs/ARCHITECTURE.md §4 and §7,
-- DECISIONS D-10, D-11, D-14, D-20, D-40, D-41.
-- =============================================================================

-- -----------------------------------------------------------------------------
-- Country packs (reference data). A new country is a new row, not new code
-- (SPEC §1.3, D-16). Tax rules stay empty (D-39).
-- -----------------------------------------------------------------------------
create table public.country_packs (
  code                 text primary key check (code ~ '^[A-Z]{2}$'),
  name_ar              text not null,
  name_en              text not null,
  currency_code        text not null check (currency_code ~ '^[A-Z]{3}$'),
  currency_minor_units smallint not null default 2 check (currency_minor_units = 2),
  default_timezone     text not null,
  default_language     text not null default 'ar' check (default_language in ('ar', 'en')),
  default_digit_style  text not null default 'WESTERN' check (default_digit_style in ('WESTERN', 'ARABIC_INDIC')),
  arabic_locale        text not null default 'ar-EG',
  einvoice_adapter     text not null default 'none',
  is_active            boolean not null default true
);

-- -----------------------------------------------------------------------------
-- Tenants and their profile (SPEC §4.1).
-- -----------------------------------------------------------------------------
create table public.tenants (
  id                uuid primary key default gen_random_uuid(),
  name_ar           text not null check (length(btrim(name_ar)) > 0),
  name_en           text,
  country_code      text not null references public.country_packs (code),
  currency_code     text not null check (currency_code ~ '^[A-Z]{3}$'),
  timezone          text not null,
  commercial_reg_no text,
  tax_reg_no        text,
  address           text,
  phones            text[] not null default '{}',
  logo_path         text,
  status            text not null default 'ACTIVE' check (status in ('ACTIVE', 'ARCHIVED')),
  created_at        timestamptz not null default now(),
  created_by        uuid,
  updated_at        timestamptz not null default now(),
  updated_by        uuid
);

-- Behavioural settings. Every option has a default, so a tenant that never
-- opens Settings still gets the documented behaviour (D-40, D-41).
create table public.tenant_settings (
  tenant_id                 uuid primary key references public.tenants (id),
  fiscal_year_start_month   smallint not null default 1 check (fiscal_year_start_month between 1 and 12),
  default_language          text not null default 'ar' check (default_language in ('ar', 'en')),
  digit_style               text not null default 'WESTERN' check (digit_style in ('WESTERN', 'ARABIC_INDIC')),
  cash_negative_policy      text not null default 'WARN' check (cash_negative_policy in ('WARN', 'BLOCK')),
  aging_thresholds          smallint[] not null default '{30,60,90}',
  attention_thresholds      jsonb not null default '{"installment_due_days": 2, "dashboard_due_hours": 48, "board_due_days": 7, "lead_idle_days": 7, "min_profit": "0.00"}',
  expected_cost_categories  text[] not null default '{}',
  partner_sees_summary      boolean not null default false,
  installment_markup_mode   text not null default 'A' check (installment_markup_mode in ('A', 'B_ENABLED')),
  profit_policy             text not null default 'PERIODIC' check (profit_policy in ('PERIODIC', 'PER_CAR')),
  distribution_frequency    text not null default 'AD_HOC' check (distribution_frequency in ('AD_HOC', 'MONTHLY', 'QUARTERLY', 'YEARLY')),
  loss_handling             text not null default 'ALLOCATE_TO_PARTNERS' check (loss_handling in ('ALLOCATE_TO_PARTNERS', 'CARRY_FORWARD')),
  prorata_method            text not null default 'DAY_WEIGHTED' check (prorata_method in ('DAY_WEIGHTED', 'SUB_PERIOD_PROFIT')),
  rounding_remainder        text not null default 'LARGEST_REMAINDER' check (rounding_remainder in ('LARGEST_REMAINDER', 'LARGEST_SHARE')),
  sale_cancellation_method  text not null default 'REFUND_LIABILITY' check (sale_cancellation_method in ('REFUND_LIABILITY', 'MIRROR')),
  overpayment_policy        text not null default 'BLOCK' check (overpayment_policy in ('BLOCK', 'ALLOW_AS_CREDIT')),
  created_at                timestamptz not null default now(),
  created_by                uuid,
  updated_at                timestamptz not null default now(),
  updated_by                uuid,
  constraint aging_thresholds_ascending check (
    array_length(aging_thresholds, 1) = 3
    and aging_thresholds[1] > 0
    and aging_thresholds[1] < aging_thresholds[2]
    and aging_thresholds[2] < aging_thresholds[3]
  )
);

-- Every tenant gets its settings row with defaults.
create or replace function private.create_tenant_settings()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
  insert into public.tenant_settings (tenant_id) values (new.id);
  return null;
end;
$$;

create trigger tenants_create_settings
  after insert on public.tenants
  for each row execute function private.create_tenant_settings();

-- -----------------------------------------------------------------------------
-- Branches (yards). Locations (workshop, external showroom...) arrive with
-- vehicles in Phase 4.
-- -----------------------------------------------------------------------------
create table public.branches (
  id          uuid primary key default gen_random_uuid(),
  tenant_id   uuid not null references public.tenants (id),
  name_ar     text not null check (length(btrim(name_ar)) > 0),
  name_en     text,
  address     text,
  is_default  boolean not null default false,
  archived_at timestamptz,
  created_at  timestamptz not null default now(),
  created_by  uuid,
  updated_at  timestamptz not null default now(),
  updated_by  uuid,
  unique (tenant_id, id)
);

create unique index branches_one_default_idx on public.branches (tenant_id) where is_default and archived_at is null;

-- -----------------------------------------------------------------------------
-- Permissions and roles (D-10, D-14). Code checks permissions, never role
-- names (SPEC §1.2). System roles have tenant_id null.
-- -----------------------------------------------------------------------------
create table public.permissions (
  code        text primary key check (code ~ '^[a-z_]+(\.[a-z_]+)+$'),
  scope       text not null default 'TENANT' check (scope in ('TENANT', 'PLATFORM')),
  description text not null
);

create table public.roles (
  id         uuid primary key default gen_random_uuid(),
  tenant_id  uuid references public.tenants (id),
  code       text not null check (code ~ '^[A-Z_]+$'),
  name_ar    text not null,
  name_en    text not null,
  is_system  boolean not null default false,
  sort_order smallint not null default 0,
  created_at timestamptz not null default now(),
  created_by uuid,
  updated_at timestamptz not null default now(),
  updated_by uuid,
  unique nulls not distinct (tenant_id, code),
  check (is_system = (tenant_id is null))
);

create table public.role_permissions (
  role_id         uuid not null references public.roles (id) on delete cascade,
  permission_code text not null references public.permissions (code),
  primary key (role_id, permission_code)
);

-- Permissions a role may never hold, whatever a tenant configures. This is how
-- "sales never sees cost" (SPEC §1.2, §10) survives tenant customisation.
create table public.role_permission_restrictions (
  role_code       text not null,
  permission_code text not null references public.permissions (code),
  reason          text not null,
  primary key (role_code, permission_code)
);

-- Per-tenant grants/revocations on top of a role bundle, e.g. "Manager may
-- post sales" (SPEC §4.7 configurable confirmer, §1.2 "finance as granted").
create table public.tenant_role_permission_overrides (
  tenant_id       uuid not null references public.tenants (id),
  role_id         uuid not null references public.roles (id),
  permission_code text not null references public.permissions (code),
  granted         boolean not null,
  created_at      timestamptz not null default now(),
  created_by      uuid,
  updated_at      timestamptz not null default now(),
  updated_by      uuid,
  primary key (tenant_id, role_id, permission_code)
);

create or replace function private.check_role_permission()
returns trigger
language plpgsql
set search_path = ''
as $$
declare
  v_role  public.roles;
  v_scope text;
begin
  select * into v_role from public.roles where id = new.role_id;
  select scope into v_scope from public.permissions where code = new.permission_code;

  if v_scope <> 'TENANT' then
    raise exception 'platform permission % cannot be assigned to a tenant role', new.permission_code
      using errcode = '23514';
  end if;

  if tg_table_name = 'tenant_role_permission_overrides' then
    if v_role.tenant_id is not null and v_role.tenant_id <> new.tenant_id then
      raise exception 'role belongs to another tenant' using errcode = '23514';
    end if;
    if not new.granted then
      return new;
    end if;
  end if;

  if exists (
    select 1 from public.role_permission_restrictions r
    where r.role_code = v_role.code and r.permission_code = new.permission_code
  ) then
    raise exception 'role % may never hold permission %', v_role.code, new.permission_code
      using errcode = '23514';
  end if;
  return new;
end;
$$;

create trigger role_permissions_check
  before insert or update on public.role_permissions
  for each row execute function private.check_role_permission();

create trigger tenant_role_permission_overrides_check
  before insert or update on public.tenant_role_permission_overrides
  for each row execute function private.check_role_permission();

-- -----------------------------------------------------------------------------
-- Memberships: user ↔ tenant with one role (A-02). partner_id gets its
-- composite FK to partners in Phase 3.
-- -----------------------------------------------------------------------------
create table public.memberships (
  id           uuid primary key default gen_random_uuid(),
  tenant_id    uuid not null references public.tenants (id),
  user_id      uuid not null references auth.users (id) on delete cascade,
  role_id      uuid not null references public.roles (id),
  partner_id   uuid,
  status       text not null default 'ACTIVE' check (status in ('ACTIVE', 'DISABLED')),
  invited_by   uuid,
  last_seen_at timestamptz,
  created_at   timestamptz not null default now(),
  created_by   uuid,
  updated_at   timestamptz not null default now(),
  updated_by   uuid,
  unique (tenant_id, user_id),
  unique (tenant_id, id)
);

create index memberships_user_idx on public.memberships (user_id) where status = 'ACTIVE';

create or replace function private.check_membership_role()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  if not exists (
    select 1 from public.roles r
    where r.id = new.role_id and (r.tenant_id is null or r.tenant_id = new.tenant_id)
  ) then
    raise exception 'role does not belong to this tenant' using errcode = '23514';
  end if;
  return new;
end;
$$;

create trigger memberships_check_role
  before insert or update of role_id, tenant_id on public.memberships
  for each row execute function private.check_membership_role();

-- -----------------------------------------------------------------------------
-- Sequential numbers per tenant (D-20): journal entry_no, stock numbers,
-- invoice numbers. Taken with SELECT ... FOR UPDATE in the posting transaction.
-- -----------------------------------------------------------------------------
create table public.tenant_counters (
  tenant_id   uuid not null references public.tenants (id),
  counter_key text not null,
  last_value  bigint not null default 0 check (last_value >= 0),
  primary key (tenant_id, counter_key)
);

-- -----------------------------------------------------------------------------
-- SaaS platform layer (SPEC §4.16). Billing is manual in the MVP.
-- -----------------------------------------------------------------------------
create table public.platform_admins (
  user_id    uuid primary key references auth.users (id) on delete cascade,
  created_at timestamptz not null default now()
);

create table public.plans (
  id         uuid primary key default gen_random_uuid(),
  code       text not null unique check (code ~ '^[A-Z_]+$'),
  name_ar    text not null,
  name_en    text not null,
  limits     jsonb not null default '{}',
  is_active  boolean not null default true,
  created_at timestamptz not null default now(),
  created_by uuid,
  updated_at timestamptz not null default now(),
  updated_by uuid
);

create table public.subscriptions (
  id                 uuid primary key default gen_random_uuid(),
  tenant_id          uuid not null unique references public.tenants (id),
  plan_id            uuid not null references public.plans (id),
  status             text not null default 'TRIAL' check (status in ('TRIAL', 'ACTIVE', 'PAST_DUE', 'SUSPENDED')),
  trial_ends_at      timestamptz,
  current_period_end timestamptz,
  created_at         timestamptz not null default now(),
  created_by         uuid,
  updated_at         timestamptz not null default now(),
  updated_by         uuid,
  unique (tenant_id, id)
);

-- A flag is set either on a plan (default) or on a tenant (override).
create table public.feature_flags (
  id         uuid primary key default gen_random_uuid(),
  plan_id    uuid references public.plans (id),
  tenant_id  uuid references public.tenants (id),
  flag_key   text not null check (flag_key ~ '^[a-z_]+$'),
  enabled    boolean not null,
  created_at timestamptz not null default now(),
  created_by uuid,
  updated_at timestamptz not null default now(),
  updated_by uuid,
  check (num_nonnulls(plan_id, tenant_id) = 1),
  unique nulls not distinct (plan_id, tenant_id, flag_key)
);

-- -----------------------------------------------------------------------------
-- Security for every table above (private.secure_table, foundation migration).
-- Settings and tenant data are written only through the API (D-04).
-- -----------------------------------------------------------------------------
call private.secure_table('public.country_packs', p_touch => false);
call private.secure_table('public.tenants');
call private.secure_table('public.tenant_settings');
call private.secure_table('public.branches');
call private.secure_table('public.permissions', p_touch => false);
call private.secure_table('public.roles');
call private.secure_table('public.role_permissions', p_touch => false);
call private.secure_table('public.role_permission_restrictions', p_touch => false);
call private.secure_table('public.tenant_role_permission_overrides');
call private.secure_table('public.memberships');
call private.secure_table('public.tenant_counters', p_touch => false, p_audit => false);
call private.secure_table('public.platform_admins', p_touch => false);
call private.secure_table('public.plans');
call private.secure_table('public.subscriptions');
call private.secure_table('public.feature_flags');

-- Counters are internal: the browser never sees them.
revoke select on table public.tenant_counters from authenticated;
-- Reference tables are read-only for the API too.
revoke insert, update on table
  public.country_packs, public.permissions, public.role_permission_restrictions, public.plans
  from app_api;
