-- =============================================================================
-- Phase 8: Excel import and onboarding (SPEC §4.13, BACKLOG 8.x).
-- Import jobs keep the uploaded sheets, the column mapping and the validated
-- rows until they are committed in one transaction with one opening entry
-- (rule 25). Mappings are remembered per tenant and header layout.
-- Design: DECISIONS D-107..D-112.
-- =============================================================================

-- Open installments imported at go-live have no sale in the system (D-107).
alter table public.installment_plans
  alter column sale_id drop not null,
  add column opening_reference text,
  add column opening_vehicle   text,
  add constraint installment_plans_origin check (sale_id is not null or opening_reference is not null);

-- A car imported with its cost has an OPENING purchase record (no seller unless one is still owed).
alter table public.vehicle_purchases
  alter column seller_customer_id drop not null,
  drop constraint vehicle_purchases_source_check,
  add constraint vehicle_purchases_source_check check (source in ('PURCHASE', 'TRADE_IN', 'OPENING')),
  add constraint vehicle_purchases_seller check (source = 'OPENING' or seller_customer_id is not null);

create table public.import_jobs (
  id             uuid primary key default gen_random_uuid(),
  tenant_id      uuid not null references public.tenants (id),
  file_name      text,
  go_live_date   date not null,
  status         text not null default 'UPLOADED' check (status in ('UPLOADED', 'VALIDATED', 'COMMITTED')),
  -- [{name, kind, header_row, headers, rows, column_map}] (raw text cells).
  sheets         jsonb not null,
  -- Per sheet: [{row_no, errors: [{field, code}]}] and the normalised records.
  validation     jsonb,
  result         jsonb,
  journal_entry_id uuid,
  committed_at   timestamptz,
  created_at     timestamptz not null default now(),
  created_by     uuid,
  updated_at     timestamptz not null default now(),
  updated_by     uuid,
  unique (tenant_id, id),
  foreign key (tenant_id, journal_entry_id) references public.journal_entries (tenant_id, id),
  check ((status = 'COMMITTED') = (committed_at is not null))
);
create index import_jobs_created_idx on public.import_jobs (tenant_id, created_at desc);

-- A committed import is history: it never changes again.
create or replace function private.import_job_before_update()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  if old.status = 'COMMITTED' then
    raise exception 'a committed import cannot be changed' using errcode = 'SR003';
  end if;
  return new;
end;
$$;
create trigger import_jobs_before_update before update on public.import_jobs
  for each row execute function private.import_job_before_update();

create table public.import_mappings (
  id         uuid primary key default gen_random_uuid(),
  tenant_id  uuid not null references public.tenants (id),
  kind       text not null check (kind in ('VEHICLES', 'CUSTOMERS', 'PARTNERS', 'INSTALLMENTS', 'CASH')),
  -- Normalised headers joined with '|': the same layout gets the same mapping.
  signature  text not null,
  column_map jsonb not null,
  created_at timestamptz not null default now(),
  created_by uuid,
  updated_at timestamptz not null default now(),
  updated_by uuid,
  unique (tenant_id, id),
  unique (tenant_id, kind, signature)
);

call private.secure_table('public.import_jobs');
call private.secure_table('public.import_mappings');

do $$
declare
  t text;
begin
  foreach t in array array['import_jobs', 'import_mappings']
  loop
    execute format(
      'create policy %I on public.%I for all to app_api
         using (tenant_id = (select private.current_tenant_id()))
         with check (tenant_id = (select private.current_tenant_id()))',
      t || '_api', t);
    execute format(
      'create policy %I on public.%I for select to authenticated
         using (tenant_id = any ((select private.tenants_with_permission(''import.run''))::uuid[]))',
      t || '_read', t);
  end loop;
end;
$$;

revoke execute on all routines in schema private from public, anon, authenticated, service_role;
grant execute on function
  private.current_tenant_id(), private.current_user_id(), private.current_actor_id(),
  private.my_tenant_ids(), private.tenants_with_permission(text), private.is_member(uuid),
  private.has_permission(uuid, text), private.has_any_permission(uuid, text[]),
  private.my_partner_id(uuid), private.is_platform_admin(), private.tenant_writable(uuid),
  private.feature_enabled(uuid, text)
  to authenticated, app_api;
grant execute on function private.active_tenant_ids(), private.paper_transition_allowed(text, text, text),
  private.match_request(uuid)
  to app_api;
