-- =============================================================================
-- Phase 7: period close and profit distribution (rules 22, 23), per-car
-- allocation in advance (D-40, P-10), loss handling (P-09).
-- Design: SPEC §4.9; ACCOUNTING rules 22, 23; DECISIONS D-29, D-40, D-100..D-104.
-- =============================================================================

-- -----------------------------------------------------------------------------
-- Distributions: one per closed period. A period cannot be distributed twice
-- (BACKLOG 7.1): posted distributions never overlap.
-- -----------------------------------------------------------------------------
create table public.profit_distributions (
  id                            uuid primary key default gen_random_uuid(),
  tenant_id                     uuid not null references public.tenants (id),
  period_from                   date not null,
  period_to                     date not null,
  profit_policy                 text not null check (profit_policy in ('PERIODIC', 'PER_CAR')),
  prorata_method                text not null check (prorata_method in ('DAY_WEIGHTED', 'SUB_PERIOD_PROFIT')),
  rounding_remainder            text not null check (rounding_remainder in ('LARGEST_REMAINDER', 'LARGEST_SHARE')),
  loss_handling                 text not null check (loss_handling in ('ALLOCATE_TO_PARTNERS', 'CARRY_FORWARD')),
  net_profit                    numeric(18, 2) not null,
  allocated_in_advance          numeric(18, 2) not null default 0,
  carried_in                    numeric(18, 2) not null default 0 check (carried_in <= 0),
  distributed                   numeric(18, 2) not null,
  closing_journal_entry_id      uuid,
  netting_journal_entry_id      uuid,
  distribution_journal_entry_id uuid,
  notes                         text,
  status                        text not null default 'POSTED' check (status in ('POSTED', 'REVERSED')),
  reversed_at                   timestamptz,
  reversed_by                   uuid,
  reversal_reason               text,
  created_at                    timestamptz not null default now(),
  created_by                    uuid,
  updated_at                    timestamptz not null default now(),
  updated_by                    uuid,
  unique (tenant_id, id),
  foreign key (tenant_id, closing_journal_entry_id) references public.journal_entries (tenant_id, id),
  foreign key (tenant_id, netting_journal_entry_id) references public.journal_entries (tenant_id, id),
  foreign key (tenant_id, distribution_journal_entry_id) references public.journal_entries (tenant_id, id),
  check (period_to >= period_from),
  check ((status = 'REVERSED') = (reversed_at is not null and reversal_reason is not null)),
  constraint profit_distributions_no_overlap exclude using gist (
    tenant_id with =,
    daterange(period_from, period_to, '[]') with &&
  ) where (status = 'POSTED')
);
create index profit_distributions_period_idx on public.profit_distributions (tenant_id, period_to desc);

-- A distribution only changes by being reversed as a whole.
create or replace function private.profit_distribution_before_update()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  if old.status = 'POSTED' and new.status = 'REVERSED'
     and (to_jsonb(new) - array['status', 'reversed_at', 'reversed_by', 'reversal_reason', 'updated_at', 'updated_by'])
       = (to_jsonb(old) - array['status', 'reversed_at', 'reversed_by', 'reversal_reason', 'updated_at', 'updated_by']) then
    return new;
  end if;
  raise exception 'a posted distribution cannot be changed; reverse it instead' using errcode = 'SR003';
end;
$$;
create trigger profit_distributions_before_update before update on public.profit_distributions
  for each row execute function private.profit_distribution_before_update();

create table public.profit_distribution_lines (
  id              uuid primary key default gen_random_uuid(),
  tenant_id       uuid not null references public.tenants (id),
  distribution_id uuid not null,
  partner_id      uuid not null,
  weight_pct      numeric(12, 8) not null,
  amount          numeric(18, 2) not null,
  unique (tenant_id, id),
  unique (distribution_id, partner_id),
  foreign key (tenant_id, distribution_id) references public.profit_distributions (tenant_id, id),
  foreign key (tenant_id, partner_id) references public.partners (tenant_id, id)
);
create trigger profit_distribution_lines_no_change before update or delete on public.profit_distribution_lines
  for each row execute function private.journal_forbid_change();

-- -----------------------------------------------------------------------------
-- Per-car policy (D-40): each posted sale allocates its gross profit to the
-- partners through 3310 at once; a cancelled sale reverses its allocation.
-- -----------------------------------------------------------------------------
create table public.profit_allocations (
  id                uuid primary key default gen_random_uuid(),
  tenant_id         uuid not null references public.tenants (id),
  sale_id           uuid not null,
  vehicle_id        uuid not null,
  allocation_date   date not null,
  gross_profit      numeric(18, 2) not null,
  status            text not null default 'POSTED' check (status in ('POSTED', 'REVERSED')),
  journal_entry_id  uuid not null,
  reversal_entry_id uuid,
  created_at        timestamptz not null default now(),
  created_by        uuid,
  updated_at        timestamptz not null default now(),
  updated_by        uuid,
  unique (tenant_id, id),
  foreign key (tenant_id, sale_id) references public.sales (tenant_id, id),
  foreign key (tenant_id, vehicle_id) references public.vehicles (tenant_id, id),
  foreign key (tenant_id, journal_entry_id) references public.journal_entries (tenant_id, id),
  foreign key (tenant_id, reversal_entry_id) references public.journal_entries (tenant_id, id),
  check ((status = 'REVERSED') = (reversal_entry_id is not null))
);
create unique index profit_allocations_one_posted_idx on public.profit_allocations (tenant_id, sale_id)
  where status = 'POSTED';
create trigger profit_allocations_before_update before update on public.profit_allocations
  for each row execute function private.posted_document_before_update();

-- -----------------------------------------------------------------------------
-- A distributed period is closed for good (D-101): only closing entries (and
-- their reversals, which keep the flag) may be dated inside it.
-- -----------------------------------------------------------------------------
create or replace function private.journal_entry_check_distributed()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_to date;
begin
  if new.is_closing then
    return new;
  end if;
  select d.period_to into v_to
    from public.profit_distributions d
   where d.tenant_id = new.tenant_id and d.status = 'POSTED'
     and new.entry_date between d.period_from and d.period_to
   limit 1;
  if v_to is not null then
    raise exception 'profit for this date has been distributed' using errcode = 'SR030',
      detail = v_to::text;
  end if;
  return new;
end;
$$;
create trigger journal_entries_check_distributed before insert on public.journal_entries
  for each row execute function private.journal_entry_check_distributed();

-- -----------------------------------------------------------------------------
-- Security.
-- -----------------------------------------------------------------------------
call private.secure_table('public.profit_distributions');
call private.secure_table('public.profit_distribution_lines', p_touch => false);
call private.secure_table('public.profit_allocations');

do $$
declare
  t text;
begin
  foreach t in array array['profit_distributions', 'profit_distribution_lines', 'profit_allocations']
  loop
    execute format(
      'create policy %I on public.%I for all to app_api
         using (tenant_id = (select private.current_tenant_id()))
         with check (tenant_id = (select private.current_tenant_id()))',
      t || '_api', t);
    execute format(
      'create policy %I on public.%I for select to authenticated
         using (tenant_id = any ((select private.tenants_with_permission(''partner.view_all''))::uuid[]))',
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
