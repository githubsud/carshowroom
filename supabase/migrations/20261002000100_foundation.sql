-- =============================================================================
-- Foundation: extensions, private schema, API role, row stamping, audit log,
-- and the standard security procedure every tenant table goes through.
-- Design: docs/ARCHITECTURE.md §3–§4, docs/ERD.md §1, DECISIONS D-08, D-11, D-37.
-- =============================================================================

create extension if not exists pgcrypto with schema extensions;
create extension if not exists btree_gist with schema extensions;
create extension if not exists pg_trgm with schema extensions;

-- Internal helpers live in "private", which PostgREST does not expose.
create schema if not exists private;
revoke all on schema private from public;
alter default privileges in schema private revoke execute on functions from public;

-- -----------------------------------------------------------------------------
-- FastAPI database role (D-08). No BYPASSRLS: its own RLS policies scope every
-- row to the tenant set in app.tenant_id. LOGIN and the password are set per
-- environment (seed.sql locally, the runbook in production), never here.
-- -----------------------------------------------------------------------------
do $$
begin
  if not exists (select 1 from pg_roles where rolname = 'app_api') then
    create role app_api nologin noinherit nobypassrls;
  end if;
end
$$;

grant usage on schema public to app_api;
grant usage on schema private to app_api, authenticated;

-- Tests and maintenance run as postgres (not a superuser on Supabase) and must
-- be able to act as app_api; SET only, without inheriting its privileges.
grant app_api to postgres with set true, inherit false;

-- -----------------------------------------------------------------------------
-- Request context. The API sets these with set_config(..., true) per
-- transaction (D-09); the browser path relies on auth.uid().
-- -----------------------------------------------------------------------------
create or replace function private.current_tenant_id()
returns uuid
language sql
stable
set search_path = ''
as $$
  select nullif(current_setting('app.tenant_id', true), '')::uuid;
$$;

create or replace function private.current_user_id()
returns uuid
language sql
stable
set search_path = ''
as $$
  select nullif(current_setting('app.user_id', true), '')::uuid;
$$;

-- The acting user for audit columns: the API user if set, else the JWT subject.
-- Reads the claims setting directly (as auth.uid() does) because app_api has
-- no access to the auth schema.
create or replace function private.current_actor_id()
returns uuid
language sql
stable
set search_path = ''
as $$
  select coalesce(
    private.current_user_id(),
    nullif(nullif(current_setting('request.jwt.claims', true), '')::jsonb ->> 'sub', '')::uuid
  );
$$;

-- Supabase grants EXECUTE on new functions to anon/authenticated/service_role
-- through global default privileges, which a per-schema default cannot undo.
-- Every migration that creates private functions therefore ends with an
-- explicit revoke and re-grants only what each role needs.
revoke execute on all routines in schema private from public, anon, authenticated, service_role;
grant execute on function private.current_tenant_id() to app_api, authenticated;
grant execute on function private.current_user_id() to app_api, authenticated;
grant execute on function private.current_actor_id() to app_api, authenticated;

-- -----------------------------------------------------------------------------
-- Row stamping: created_* are set once, updated_* on every write.
-- -----------------------------------------------------------------------------
create or replace function private.touch_row()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  if tg_op = 'INSERT' then
    new.created_at := now();
    new.created_by := coalesce(private.current_actor_id(), new.created_by);
  else
    new.created_at := old.created_at;
    new.created_by := old.created_by;
  end if;
  new.updated_at := now();
  new.updated_by := coalesce(private.current_actor_id(), new.updated_by);
  return new;
end;
$$;

-- -----------------------------------------------------------------------------
-- Audit log (SPEC §4.15): append-only for every role, including the owner.
-- D-37 calls for monthly partitioning; it is deferred to Phase 9 hardening,
-- when real volumes are known (documented in DECISIONS.md).
-- -----------------------------------------------------------------------------
create table public.audit_log (
  id            bigint generated always as identity primary key,
  tenant_id     uuid,
  actor_user_id uuid,
  actor_kind    text not null check (actor_kind in ('USER', 'PLATFORM', 'SYSTEM')),
  action        text not null,
  entity_type   text,
  entity_id     text,
  before        jsonb,
  after         jsonb,
  details       jsonb,
  ip            inet,
  user_agent    text,
  request_id    text,
  occurred_at   timestamptz not null default now()
);

create index audit_log_tenant_time_idx on public.audit_log (tenant_id, occurred_at desc);
create index audit_log_entity_idx on public.audit_log (tenant_id, entity_type, entity_id);

create or replace function private.forbid_audit_change()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  raise exception 'audit_log is append-only' using errcode = '42501';
end;
$$;

create trigger audit_log_no_update_delete
  before update or delete on public.audit_log
  for each row execute function private.forbid_audit_change();

create trigger audit_log_no_truncate
  before truncate on public.audit_log
  for each statement execute function private.forbid_audit_change();

-- Generic row-change capture. SECURITY DEFINER so it can append to audit_log
-- although no client role holds INSERT on it.
create or replace function private.audit_row_change()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_old   jsonb := case when tg_op in ('UPDATE', 'DELETE') then to_jsonb(old) end;
  v_new   jsonb := case when tg_op in ('INSERT', 'UPDATE') then to_jsonb(new) end;
  v_row   jsonb := coalesce(v_new, v_old);
  v_actor uuid  := private.current_actor_id();
begin
  if tg_op = 'UPDATE' and v_old = v_new then
    return null;
  end if;

  insert into public.audit_log (
    tenant_id, actor_user_id, actor_kind, action, entity_type, entity_id,
    before, after, request_id, ip, user_agent
  ) values (
    case when tg_table_name = 'tenants' then (v_row ->> 'id')::uuid
         else (v_row ->> 'tenant_id')::uuid end,
    v_actor,
    case when v_actor is null then 'SYSTEM' else 'USER' end,
    tg_op,
    tg_table_name,
    coalesce(v_row ->> 'id', v_row ->> 'tenant_id', v_row ->> 'role_id', v_row ->> 'user_id'),
    v_old,
    v_new,
    nullif(current_setting('app.request_id', true), ''),
    nullif(current_setting('app.client_ip', true), '')::inet,
    nullif(current_setting('app.user_agent', true), '')
  );
  return null;
end;
$$;

-- -----------------------------------------------------------------------------
-- Standard security for a table (ARCHITECTURE §3):
--   * RLS on; anon, authenticated and service_role lose Supabase's default grants
--   * authenticated may SELECT (RLS decides which rows); INSERT/UPDATE only for
--     non-financial tables the browser edits directly
--   * app_api may SELECT/INSERT/UPDATE (RLS scopes it to app.tenant_id)
--   * row stamping and audit triggers attached
-- Physical DELETE is never granted to client roles: master data is archived.
-- -----------------------------------------------------------------------------
create or replace procedure private.secure_table(
  p_table         regclass,
  p_browser_write boolean default false,
  p_touch         boolean default true,
  p_audit         boolean default true
)
language plpgsql
set search_path = ''
as $$
begin
  execute format('alter table %s enable row level security', p_table);
  execute format('revoke all on table %s from anon, authenticated, service_role, app_api', p_table);
  execute format('grant select on table %s to authenticated', p_table);
  if p_browser_write then
    execute format('grant insert, update on table %s to authenticated', p_table);
  end if;
  execute format('grant select, insert, update on table %s to app_api', p_table);
  if p_touch then
    execute format(
      'create trigger touch_row before insert or update on %s for each row execute function private.touch_row()',
      p_table);
  end if;
  if p_audit then
    execute format(
      'create trigger audit_row after insert or update or delete on %s for each row execute function private.audit_row_change()',
      p_table);
  end if;
end;
$$;

-- audit_log itself: readable under RLS, never writable by clients.
alter table public.audit_log enable row level security;
revoke all on table public.audit_log from anon, authenticated, service_role, app_api;
grant select on table public.audit_log to authenticated, app_api;
-- The API records events (login, invitations, permission changes) directly.
grant insert on table public.audit_log to app_api;
