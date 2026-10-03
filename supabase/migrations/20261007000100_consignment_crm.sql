-- =============================================================================
-- Phase 6: consignment in and out, external showrooms, follow-ups, customer
-- requests and matching.
-- Design: SPEC §4.4-§4.6; docs/ERD.md §4, §5; ACCOUNTING rules 10, 16-19, 30,
-- 31 (C-11), P-05, P-06; DECISIONS D-22, D-35, D-91..D-99; Q-15, Q-33, Q-34.
-- =============================================================================

-- Showroom-borne expenses on consigned cars (P-05, approved 2026-10-02).
insert into public.coa_template (code, parent_code, name_ar, name_en, type, normal_side, is_postable, subledger, system_key)
values ('6280', '6200', 'مصاريف سيارات الأمانة على المعرض', 'Consigned-car expenses borne by the showroom', 'EXPENSE',
        'DEBIT', true, 'VEHICLE', 'EXP_CONSIGNMENT')
on conflict do nothing;

insert into public.ledger_accounts
  (tenant_id, code, parent_id, name_ar, name_en, type, normal_side, is_postable, is_system, subledger, system_key)
select t.id, '6280', parent.id, 'مصاريف سيارات الأمانة على المعرض', 'Consigned-car expenses borne by the showroom',
       'EXPENSE', 'DEBIT', true, true, 'VEHICLE', 'EXP_CONSIGNMENT'
  from public.tenants t
  join public.ledger_accounts parent on parent.tenant_id = t.id and parent.system_key = 'GENERAL_EXPENSES'
 where not exists (select 1 from public.ledger_accounts a where a.tenant_id = t.id and a.system_key = 'EXP_CONSIGNMENT');

-- -----------------------------------------------------------------------------
-- External showrooms (SPEC §4.5) and their locations.
-- -----------------------------------------------------------------------------
create table public.external_showrooms (
  id           uuid primary key default gen_random_uuid(),
  tenant_id    uuid not null references public.tenants (id),
  name         text not null check (length(btrim(name)) > 0),
  contact_name text,
  phone        text,
  address      text,
  notes        text,
  archived_at  timestamptz,
  created_at   timestamptz not null default now(),
  created_by   uuid,
  updated_at   timestamptz not null default now(),
  updated_by   uuid,
  unique (tenant_id, id)
);

alter table public.locations
  add column external_showroom_id uuid,
  add constraint locations_external_fk
    foreign key (tenant_id, external_showroom_id) references public.external_showrooms (tenant_id, id);

-- Journal subledgers: consignors are customers (A-06); external showrooms are their own records.
alter table public.journal_lines
  add constraint journal_lines_consignor_fk
    foreign key (tenant_id, consignor_id) references public.customers (tenant_id, id),
  add constraint journal_lines_external_fk
    foreign key (tenant_id, external_showroom_id) references public.external_showrooms (tenant_id, id);

-- -----------------------------------------------------------------------------
-- Consignment IN (SPEC §4.4).
-- -----------------------------------------------------------------------------
create table public.consignments_in (
  id                uuid primary key default gen_random_uuid(),
  tenant_id         uuid not null references public.tenants (id),
  vehicle_id        uuid not null,
  consignor_id      uuid not null,
  agreement_date    date not null,
  end_date          date,
  terms_type        text not null check (terms_type in ('NET_PRICE', 'COMMISSION_FIXED', 'COMMISSION_PCT')),
  net_price_to_owner numeric(18, 2) check (net_price_to_owner > 0),
  -- A sale must leave the showroom something: net-price sales must exceed the net (Q-15 default).
  commission_value  numeric(18, 2) check (commission_value > 0),
  expenses_borne_by text not null default 'OWNER' check (expenses_borne_by in ('OWNER', 'SHOWROOM', 'SHARED')),
  shared_owner_pct  numeric(5, 2) check (shared_owner_pct > 0 and shared_owner_pct < 100),
  notes             text,
  status            text not null default 'ACTIVE' check (status in ('ACTIVE', 'SOLD', 'RETURNED')),
  returned_date     date,
  created_at        timestamptz not null default now(),
  created_by        uuid,
  updated_at        timestamptz not null default now(),
  updated_by        uuid,
  unique (tenant_id, id),
  foreign key (tenant_id, vehicle_id) references public.vehicles (tenant_id, id),
  foreign key (tenant_id, consignor_id) references public.customers (tenant_id, id),
  check (end_date is null or end_date >= agreement_date),
  check ((terms_type = 'NET_PRICE') = (net_price_to_owner is not null)),
  check ((terms_type <> 'NET_PRICE') = (commission_value is not null)),
  check (terms_type <> 'COMMISSION_PCT' or commission_value <= 100),
  check ((expenses_borne_by = 'SHARED') = (shared_owner_pct is not null)),
  check ((status = 'RETURNED') = (returned_date is not null))
);
create unique index consignments_in_vehicle_idx on public.consignments_in (tenant_id, vehicle_id);
create index consignments_in_consignor_idx on public.consignments_in (tenant_id, consignor_id);

-- Settlements with the owner: payouts (rule 17) and recovery of expenses (P-06).
create table public.consignor_settlements (
  id                uuid primary key default gen_random_uuid(),
  tenant_id         uuid not null references public.tenants (id),
  consignment_id    uuid not null,
  kind              text not null check (kind in ('PAYOUT', 'RECOVERY')),
  settle_date       date not null,
  amount            numeric(18, 2) not null check (amount > 0),
  cash_account_id   uuid not null,
  notes             text,
  status            text not null default 'POSTED' check (status in ('POSTED', 'REVERSED')),
  journal_entry_id  uuid not null,
  reversal_entry_id uuid,
  created_at        timestamptz not null default now(),
  created_by        uuid,
  updated_at        timestamptz not null default now(),
  updated_by        uuid,
  unique (tenant_id, id),
  foreign key (tenant_id, consignment_id) references public.consignments_in (tenant_id, id),
  foreign key (tenant_id, cash_account_id) references public.cash_accounts (tenant_id, id),
  foreign key (tenant_id, journal_entry_id) references public.journal_entries (tenant_id, id),
  foreign key (tenant_id, reversal_entry_id) references public.journal_entries (tenant_id, id),
  check ((status = 'REVERSED') = (reversal_entry_id is not null))
);
create trigger consignor_settlements_before_update before update on public.consignor_settlements
  for each row execute function private.posted_document_before_update();

-- How an expense on a consigned car is carried (rule 10 / P-05).
alter table public.vehicle_expenses drop constraint vehicle_expenses_treatment_check;
alter table public.vehicle_expenses add constraint vehicle_expenses_treatment_check
  check (treatment in ('CAPITALIZE', 'COGS', 'RECOVERABLE', 'SHOWROOM', 'SHARED'));

-- -----------------------------------------------------------------------------
-- Consignment OUT (SPEC §4.5) and collections (rule 19).
-- -----------------------------------------------------------------------------
create table public.consignments_out (
  id                   uuid primary key default gen_random_uuid(),
  tenant_id            uuid not null references public.tenants (id),
  vehicle_id           uuid not null,
  external_showroom_id uuid not null,
  sent_date            date not null,
  commission_type      text not null check (commission_type in ('FIXED', 'PCT')),
  commission_value     numeric(18, 2) not null check (commission_value >= 0),
  expected_price       numeric(18, 2) check (expected_price > 0),
  notes                text,
  status               text not null default 'OUT' check (status in ('OUT', 'SOLD', 'RETURNED')),
  returned_date        date,
  sale_id              uuid,
  created_at           timestamptz not null default now(),
  created_by           uuid,
  updated_at           timestamptz not null default now(),
  updated_by           uuid,
  unique (tenant_id, id),
  foreign key (tenant_id, vehicle_id) references public.vehicles (tenant_id, id),
  foreign key (tenant_id, external_showroom_id) references public.external_showrooms (tenant_id, id),
  foreign key (tenant_id, sale_id) references public.sales (tenant_id, id),
  check (commission_type <> 'PCT' or commission_value <= 100),
  check ((status = 'RETURNED') = (returned_date is not null)),
  check ((status = 'SOLD') = (sale_id is not null))
);
create unique index consignments_out_one_open_idx on public.consignments_out (tenant_id, vehicle_id) where status = 'OUT';
create index consignments_out_showroom_idx on public.consignments_out (tenant_id, external_showroom_id, status);

create table public.external_collections (
  id                   uuid primary key default gen_random_uuid(),
  tenant_id            uuid not null references public.tenants (id),
  external_showroom_id uuid not null,
  collect_date         date not null,
  amount               numeric(18, 2) not null check (amount > 0),
  cash_account_id      uuid not null,
  notes                text,
  status               text not null default 'POSTED' check (status in ('POSTED', 'REVERSED')),
  journal_entry_id     uuid not null,
  reversal_entry_id    uuid,
  created_at           timestamptz not null default now(),
  created_by           uuid,
  updated_at           timestamptz not null default now(),
  updated_by           uuid,
  unique (tenant_id, id),
  foreign key (tenant_id, external_showroom_id) references public.external_showrooms (tenant_id, id),
  foreign key (tenant_id, cash_account_id) references public.cash_accounts (tenant_id, id),
  foreign key (tenant_id, journal_entry_id) references public.journal_entries (tenant_id, id),
  foreign key (tenant_id, reversal_entry_id) references public.journal_entries (tenant_id, id),
  check ((status = 'REVERSED') = (reversal_entry_id is not null))
);
create trigger external_collections_before_update before update on public.external_collections
  for each row execute function private.posted_document_before_update();

-- A sale by an external showroom is a sales row with channel EXTERNAL_SHOWROOM (D-35):
-- the buyer may be unknown, no invoice is issued by us, and the commission has its own entry.
alter table public.sales
  alter column buyer_customer_id drop not null,
  add column external_showroom_id uuid,
  add column external_commission numeric(18, 2) not null default 0 check (external_commission >= 0),
  add column commission_journal_entry_id uuid,
  add constraint sales_external_fk
    foreign key (tenant_id, external_showroom_id) references public.external_showrooms (tenant_id, id),
  add constraint sales_commission_entry_fk
    foreign key (tenant_id, commission_journal_entry_id) references public.journal_entries (tenant_id, id),
  add constraint sales_channel_parties check (
    (channel = 'DIRECT' and buyer_customer_id is not null and external_showroom_id is null)
    or (channel = 'EXTERNAL_SHOWROOM' and external_showroom_id is not null)
  );
alter table public.sales drop constraint sales_check2;
alter table public.sales add constraint sales_posted_complete check (
  status = 'DRAFT' or (journal_entry_id is not null and cost_journal_entry_id is not null and posted_at is not null
                       and (channel = 'EXTERNAL_SHOWROOM' or invoice_no is not null))
);

-- -----------------------------------------------------------------------------
-- Follow-ups (D-22: SPEC call_logs) and customer requests with matching (§4.6).
-- -----------------------------------------------------------------------------
create table public.customer_requests (
  id               uuid primary key default gen_random_uuid(),
  tenant_id        uuid not null references public.tenants (id),
  customer_id      uuid not null,
  make             text,
  model            text,
  year_from        smallint check (year_from between 1950 and 2100),
  year_to          smallint check (year_to between 1950 and 2100),
  budget_min       numeric(18, 2) check (budget_min >= 0),
  budget_max       numeric(18, 2) check (budget_max >= 0),
  color_pref       text,
  notes            text,
  status           text not null default 'NEW'
                   check (status in ('NEW', 'CONTACTED', 'VEHICLE_FOUND', 'NEGOTIATING', 'DEPOSIT', 'WON', 'LOST', 'ON_HOLD')),
  assigned_to      uuid,
  source           text,
  financing_needed boolean not null default false,
  trade_in_offered boolean not null default false,
  created_at       timestamptz not null default now(),
  created_by       uuid,
  updated_at       timestamptz not null default now(),
  updated_by       uuid,
  unique (tenant_id, id),
  foreign key (tenant_id, customer_id) references public.customers (tenant_id, id),
  check (year_from is null or year_to is null or year_from <= year_to),
  check (budget_min is null or budget_max is null or budget_min <= budget_max),
  check (make is not null or model is not null)
);
create index customer_requests_open_idx on public.customer_requests (tenant_id, status, make);

create table public.customer_request_matches (
  id           uuid primary key default gen_random_uuid(),
  tenant_id    uuid not null references public.tenants (id),
  request_id   uuid not null,
  vehicle_id   uuid not null,
  matched_at   timestamptz not null default now(),
  contacted    boolean not null default false,
  contacted_by uuid,
  contacted_at timestamptz,
  unique (tenant_id, id),
  unique (request_id, vehicle_id),
  foreign key (tenant_id, request_id) references public.customer_requests (tenant_id, id),
  foreign key (tenant_id, vehicle_id) references public.vehicles (tenant_id, id)
);
create index customer_request_matches_vehicle_idx on public.customer_request_matches (tenant_id, vehicle_id);

create table public.follow_ups (
  id                 uuid primary key default gen_random_uuid(),
  tenant_id          uuid not null references public.tenants (id),
  customer_id        uuid not null,
  request_id         uuid,
  kind               text not null default 'CALL' check (kind in ('CALL', 'VISIT', 'TEST_DRIVE', 'NOTE')),
  occurred_at        timestamptz not null default clock_timestamp(),
  result             text check (result in ('ANSWERED', 'NO_ANSWER', 'INTERESTED', 'NOT_INTERESTED', 'CALL_BACK', 'OTHER')),
  notes              text,
  next_action        text,
  next_follow_up_date date,
  assigned_to        uuid,
  priority           text not null default 'NORMAL' check (priority in ('LOW', 'NORMAL', 'HIGH')),
  created_at         timestamptz not null default now(),
  created_by         uuid default private.current_actor_id(),
  unique (tenant_id, id),
  foreign key (tenant_id, customer_id) references public.customers (tenant_id, id),
  foreign key (tenant_id, request_id) references public.customer_requests (tenant_id, id)
);
create index follow_ups_customer_idx on public.follow_ups (tenant_id, customer_id, occurred_at desc);
create index follow_ups_due_idx on public.follow_ups (tenant_id, next_follow_up_date);
-- A logged call is a record of what happened: never edited, never deleted.
create trigger follow_ups_no_change before update or delete on public.follow_ups
  for each row execute function private.journal_forbid_change();

-- Matching (SPEC §4.6): an open request fits a car on make, model (contained),
-- year range and budget ceiling. Colour is a preference, not a filter (D-97).
create or replace function private.request_fits(r public.customer_requests, v public.vehicles)
returns boolean
language sql
immutable
set search_path = ''
as $$
  select r.status in ('NEW', 'CONTACTED', 'VEHICLE_FOUND', 'NEGOTIATING')
     and (r.make is null or lower(btrim(r.make)) = lower(btrim(v.make)))
     and (r.model is null or v.model ilike '%' || btrim(r.model) || '%')
     and (r.year_from is null or coalesce(v.year >= r.year_from, false))
     and (r.year_to is null or coalesce(v.year <= r.year_to, false))
     and (r.budget_max is null or v.asking_price is null or v.asking_price <= r.budget_max);
$$;

-- Match one request against the cars available now; returns the number of new matches.
create or replace function private.match_request(p_request uuid)
returns integer
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_count integer;
begin
  insert into public.customer_request_matches (tenant_id, request_id, vehicle_id)
  select r.tenant_id, r.id, v.id
    from public.customer_requests r
    join public.vehicles v on v.tenant_id = r.tenant_id and v.status = 'AVAILABLE'
   where r.id = p_request and private.request_fits(r, v)
  on conflict (request_id, vehicle_id) do nothing;
  get diagnostics v_count = row_count;
  return v_count;
end;
$$;

-- A car becoming AVAILABLE is matched against every open request; members who
-- manage requests are told how many customers asked for it (BACKLOG 6.6).
create or replace function private.vehicle_available_match()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_new integer;
  v_total integer;
begin
  insert into public.customer_request_matches (tenant_id, request_id, vehicle_id)
  select r.tenant_id, r.id, new.id
    from public.customer_requests r
   where r.tenant_id = new.tenant_id and private.request_fits(r, new)
  on conflict (request_id, vehicle_id) do nothing;
  get diagnostics v_new = row_count;
  if v_new > 0 then
    select count(*) into v_total
      from public.customer_request_matches m join public.customer_requests r on r.id = m.request_id
     where m.vehicle_id = new.id and private.request_fits(r, new);
    insert into public.notifications (tenant_id, user_id, kind, params, entity_type, entity_id, dedupe_key)
    select m.tenant_id, m.user_id, 'REQUEST_MATCH',
           jsonb_build_object('stock_no', new.stock_no, 'vehicle_label', concat_ws(' ', new.make, new.model, new.year),
                              'count', v_total),
           'VEHICLE', new.id, format('match:%s:%s', new.id, txid_current())
      from public.memberships m
     where m.tenant_id = new.tenant_id and m.status = 'ACTIVE'
       and 'request.manage' = any (private.effective_permissions(m.tenant_id, m.user_id))
    on conflict (tenant_id, user_id, dedupe_key) do nothing;
  end if;
  return null;
end;
$$;

create trigger vehicles_available_match after update of status on public.vehicles
  for each row when (new.status = 'AVAILABLE' and old.status is distinct from 'AVAILABLE')
  execute function private.vehicle_available_match();

-- -----------------------------------------------------------------------------
-- Security.
-- -----------------------------------------------------------------------------
call private.secure_table('public.external_showrooms');
call private.secure_table('public.consignments_in');
call private.secure_table('public.consignor_settlements');
call private.secure_table('public.consignments_out');
call private.secure_table('public.external_collections');
call private.secure_table('public.customer_requests');
call private.secure_table('public.customer_request_matches', p_touch => false);
call private.secure_table('public.follow_ups', p_touch => false);

do $$
declare
  t text;
begin
  foreach t in array array[
    'external_showrooms', 'consignments_in', 'consignor_settlements', 'consignments_out', 'external_collections',
    'customer_requests', 'customer_request_matches', 'follow_ups']
  loop
    execute format(
      'create policy %I on public.%I for all to app_api
         using (tenant_id = (select private.current_tenant_id()))
         with check (tenant_id = (select private.current_tenant_id()))',
      t || '_api', t);
  end loop;
end;
$$;

create policy external_showrooms_read on public.external_showrooms for select to authenticated
  using (tenant_id = any ((select private.tenants_with_permission('consignment.manage'))::uuid[]));
-- Consignment agreements carry no cost of ours, but the money with the owner is financial.
create policy consignments_in_read on public.consignments_in for select to authenticated
  using (tenant_id = any ((select private.tenants_with_permission('consignment.manage'))::uuid[]));
create policy consignor_settlements_read on public.consignor_settlements for select to authenticated
  using (tenant_id = any ((select private.tenants_with_permission('consignment.settle'))::uuid[]));
create policy consignments_out_read on public.consignments_out for select to authenticated
  using (tenant_id = any ((select private.tenants_with_permission('consignment.manage'))::uuid[]));
create policy external_collections_read on public.external_collections for select to authenticated
  using (tenant_id = any ((select private.tenants_with_permission('consignment.settle'))::uuid[]));
create policy customer_requests_read on public.customer_requests for select to authenticated
  using (tenant_id = any ((select private.tenants_with_permission('customer.view'))::uuid[]));
create policy customer_request_matches_read on public.customer_request_matches for select to authenticated
  using (tenant_id = any ((select private.tenants_with_permission('customer.view'))::uuid[]));
create policy follow_ups_read on public.follow_ups for select to authenticated
  using (tenant_id = any ((select private.tenants_with_permission('customer.view'))::uuid[]));

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
