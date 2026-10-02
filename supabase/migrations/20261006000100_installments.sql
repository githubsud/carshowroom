-- =============================================================================
-- Phase 5: installment plans, receipts and allocations, deferred papers
-- (promissory notes and post-dated cheques), notifications and reminder jobs.
-- Design: SPEC §4.8, §4.17; docs/ERD.md §6, §8; ACCOUNTING rules 13, 15, 27,
-- P-02, P-03, P-07; DECISIONS A-10, D-24, D-41, D-82..D-90.
-- =============================================================================

-- -----------------------------------------------------------------------------
-- Bank charges on a bounced cheque (P-07, approved 2026-10-02) need an expense
-- account the chart did not have: 6270 under general expenses.
-- -----------------------------------------------------------------------------
insert into public.coa_template (code, parent_code, name_ar, name_en, type, normal_side, is_postable, subledger, system_key)
values ('6270', '6200', 'مصاريف بنكية', 'Bank charges', 'EXPENSE', 'DEBIT', true, 'NONE', 'EXP_BANK_CHARGES')
on conflict do nothing;

insert into public.ledger_accounts
  (tenant_id, code, parent_id, name_ar, name_en, type, normal_side, is_postable, is_system, subledger, system_key)
select t.id, '6270', parent.id, 'مصاريف بنكية', 'Bank charges', 'EXPENSE', 'DEBIT', true, true, 'NONE', 'EXP_BANK_CHARGES'
  from public.tenants t
  join public.ledger_accounts parent on parent.tenant_id = t.id and parent.system_key = 'GENERAL_EXPENSES'
 where not exists (select 1 from public.ledger_accounts a where a.tenant_id = t.id and a.system_key = 'EXP_BANK_CHARGES');

-- -----------------------------------------------------------------------------
-- Sales financed by installments (rule 13, mode a). The draft keeps the plan
-- as JSON; posting creates the plan and its installments.
-- -----------------------------------------------------------------------------
alter table public.sales
  add column receivable_amount numeric(18, 2) not null default 0 check (receivable_amount >= 0),
  add column installment_plan  jsonb;

create table public.installment_plans (
  id              uuid primary key default gen_random_uuid(),
  tenant_id       uuid not null references public.tenants (id),
  sale_id         uuid not null,
  customer_id     uuid not null,
  mode            text not null default 'A' check (mode in ('A', 'B')),
  financed_amount numeric(18, 2) not null check (financed_amount > 0),
  frequency       text not null check (frequency in ('MONTHLY', 'BIWEEKLY', 'WEEKLY', 'QUARTERLY', 'MANUAL')),
  installment_count smallint not null check (installment_count between 1 and 360),
  first_due_date  date not null,
  status          text not null default 'ACTIVE' check (status in ('ACTIVE', 'CANCELLED')),
  created_at      timestamptz not null default now(),
  created_by      uuid,
  updated_at      timestamptz not null default now(),
  updated_by      uuid,
  unique (tenant_id, id),
  unique (tenant_id, sale_id),
  foreign key (tenant_id, sale_id) references public.sales (tenant_id, id),
  foreign key (tenant_id, customer_id) references public.customers (tenant_id, id)
);
create index installment_plans_customer_idx on public.installment_plans (tenant_id, customer_id);

-- Remaining is never stored (business rule 4): see installment_status below.
create table public.installments (
  id         uuid primary key default gen_random_uuid(),
  tenant_id  uuid not null references public.tenants (id),
  plan_id    uuid not null,
  seq        smallint not null check (seq > 0),
  due_date   date not null,
  amount_due numeric(18, 2) not null check (amount_due > 0),
  created_at timestamptz not null default now(),
  unique (tenant_id, id),
  unique (plan_id, seq),
  foreign key (tenant_id, plan_id) references public.installment_plans (tenant_id, id)
);
create index installments_due_idx on public.installments (tenant_id, due_date);

-- Plans: only ACTIVE -> CANCELLED (with the sale's cancellation).
create or replace function private.installment_plan_before_update()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  if old.status = 'ACTIVE' and new.status = 'CANCELLED'
     and (to_jsonb(new) - array['status', 'updated_at', 'updated_by'])
       = (to_jsonb(old) - array['status', 'updated_at', 'updated_by']) then
    return new;
  end if;
  raise exception 'installment plans cannot be changed' using errcode = 'SR003';
end;
$$;

create trigger installment_plans_before_update before update on public.installment_plans
  for each row execute function private.installment_plan_before_update();
create trigger installment_plans_no_delete before delete on public.installment_plans
  for each row execute function private.journal_forbid_change();
create trigger installments_no_change before update or delete on public.installments
  for each row execute function private.journal_forbid_change();

-- -----------------------------------------------------------------------------
-- Deferred papers register (D-24): promissory notes and post-dated cheques.
-- OVERDUE is derived (C-10), not stored.
-- -----------------------------------------------------------------------------
create table public.deferred_papers (
  id               uuid primary key default gen_random_uuid(),
  tenant_id        uuid not null references public.tenants (id),
  paper_type       text not null check (paper_type in ('PROMISSORY_NOTE', 'PDC')),
  number           text not null check (length(btrim(number)) > 0),
  customer_id      uuid not null,
  installment_id   uuid,
  amount           numeric(18, 2) not null check (amount > 0),
  issue_date       date,
  due_date         date not null,
  storage_location text,
  drawer_bank      text,
  drawer_branch    text,
  account_holder   text,
  status           text not null default 'HELD'
                   check (status in ('HELD', 'DEPOSITED', 'COLLECTED', 'BOUNCED', 'RETURNED', 'DEFAULTED', 'LEGAL')),
  receipt_id       uuid,
  notes            text,
  created_at       timestamptz not null default now(),
  created_by       uuid,
  updated_at       timestamptz not null default now(),
  updated_by       uuid,
  unique (tenant_id, id),
  foreign key (tenant_id, customer_id) references public.customers (tenant_id, id),
  foreign key (tenant_id, installment_id) references public.installments (tenant_id, id),
  check (paper_type = 'PDC' or status not in ('DEPOSITED', 'COLLECTED', 'BOUNCED'))
);
create index deferred_papers_due_idx on public.deferred_papers (tenant_id, status, due_date);
create unique index deferred_papers_number_idx on public.deferred_papers (tenant_id, paper_type, number, coalesce(drawer_bank, ''));

create table public.deferred_paper_events (
  id          uuid primary key default gen_random_uuid(),
  tenant_id   uuid not null references public.tenants (id),
  paper_id    uuid not null,
  from_status text,
  to_status   text not null,
  event_date  date not null,
  note        text,
  entry_id    uuid,
  created_at  timestamptz not null default clock_timestamp(),
  created_by  uuid,
  unique (tenant_id, id),
  foreign key (tenant_id, paper_id) references public.deferred_papers (tenant_id, id),
  foreign key (tenant_id, entry_id) references public.journal_entries (tenant_id, id)
);
create index deferred_paper_events_paper_idx on public.deferred_paper_events (tenant_id, paper_id, created_at);
create trigger deferred_paper_events_no_change before update or delete on public.deferred_paper_events
  for each row execute function private.journal_forbid_change();
create trigger deferred_papers_no_delete before delete on public.deferred_papers
  for each row execute function private.journal_forbid_change();

-- The physical life of a paper (SPEC §4.8). Cheques can be deposited, collected
-- or bounce; a bounced cheque can be presented again.
create or replace function private.paper_transition_allowed(p_type text, p_from text, p_to text)
returns boolean
language sql
immutable
set search_path = ''
as $$
  select (p_from || '>' || p_to) = any (
    case when p_type = 'PDC' then array[
      'HELD>DEPOSITED', 'HELD>COLLECTED', 'DEPOSITED>COLLECTED', 'DEPOSITED>BOUNCED', 'COLLECTED>BOUNCED',
      'BOUNCED>DEPOSITED', 'BOUNCED>LEGAL', 'BOUNCED>RETURNED', 'HELD>RETURNED', 'HELD>DEFAULTED',
      'DEFAULTED>LEGAL', 'DEFAULTED>RETURNED', 'LEGAL>RETURNED']
    else array['HELD>RETURNED', 'HELD>DEFAULTED', 'DEFAULTED>LEGAL', 'DEFAULTED>RETURNED', 'LEGAL>RETURNED'] end);
$$;

create or replace function private.deferred_paper_before_update()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
  if new.paper_type <> old.paper_type or new.customer_id <> old.customer_id or new.amount <> old.amount
     or new.tenant_id <> old.tenant_id then
    raise exception 'a paper''s type, customer and amount never change' using errcode = 'SR003';
  end if;
  if new.status <> old.status and not private.paper_transition_allowed(old.paper_type, old.status, new.status) then
    raise exception 'paper cannot move from % to %', old.status, new.status
      using errcode = 'SR021', detail = format('%s>%s', old.status, new.status);
  end if;
  return new;
end;
$$;

create trigger deferred_papers_before_update before update on public.deferred_papers
  for each row execute function private.deferred_paper_before_update();

-- -----------------------------------------------------------------------------
-- Receipts (rule 15) and their allocation to installments. A receipt is paid
-- from a cash box / bank, from the customer's credit, or by a collected cheque.
-- BOUNCED: the cheque behind it bounced after collection (rule 27); its
-- allocations no longer count, so the installments reopen.
-- -----------------------------------------------------------------------------
create table public.customer_receipts (
  id                uuid primary key default gen_random_uuid(),
  tenant_id         uuid not null references public.tenants (id),
  customer_id       uuid not null,
  plan_id           uuid not null,
  receipt_date      date not null,
  amount            numeric(18, 2) not null check (amount > 0),
  source            text not null check (source in ('CASH_ACCOUNT', 'CREDIT', 'PAPER')),
  cash_account_id   uuid,
  deferred_paper_id uuid,
  excess_to_credit  numeric(18, 2) not null default 0 check (excess_to_credit >= 0),
  notes             text,
  status            text not null default 'POSTED' check (status in ('POSTED', 'REVERSED', 'BOUNCED')),
  journal_entry_id  uuid not null,
  reversal_entry_id uuid,
  bounce_entry_id   uuid,
  created_at        timestamptz not null default now(),
  created_by        uuid,
  updated_at        timestamptz not null default now(),
  updated_by        uuid,
  unique (tenant_id, id),
  foreign key (tenant_id, customer_id) references public.customers (tenant_id, id),
  foreign key (tenant_id, plan_id) references public.installment_plans (tenant_id, id),
  foreign key (tenant_id, cash_account_id) references public.cash_accounts (tenant_id, id),
  foreign key (tenant_id, deferred_paper_id) references public.deferred_papers (tenant_id, id),
  foreign key (tenant_id, journal_entry_id) references public.journal_entries (tenant_id, id),
  foreign key (tenant_id, reversal_entry_id) references public.journal_entries (tenant_id, id),
  foreign key (tenant_id, bounce_entry_id) references public.journal_entries (tenant_id, id),
  check ((source = 'CREDIT') = (cash_account_id is null)),
  check ((source = 'PAPER') = (deferred_paper_id is not null)),
  check (excess_to_credit < amount),
  check ((status = 'REVERSED') = (reversal_entry_id is not null)),
  check ((status = 'BOUNCED') = (bounce_entry_id is not null))
);
create index customer_receipts_plan_idx on public.customer_receipts (tenant_id, plan_id, receipt_date);

alter table public.deferred_papers
  add constraint deferred_papers_receipt_fk
  foreign key (tenant_id, receipt_id) references public.customer_receipts (tenant_id, id);

create or replace function private.receipt_before_update()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  if old.status = 'POSTED'
     and ((new.status = 'REVERSED' and new.reversal_entry_id is not null)
          or (new.status = 'BOUNCED' and new.bounce_entry_id is not null))
     and (to_jsonb(new) - array['status', 'reversal_entry_id', 'bounce_entry_id', 'updated_at', 'updated_by'])
       = (to_jsonb(old) - array['status', 'reversal_entry_id', 'bounce_entry_id', 'updated_at', 'updated_by']) then
    return new;
  end if;
  raise exception 'posted receipts cannot be changed; reverse them instead' using errcode = 'SR003';
end;
$$;

create trigger customer_receipts_before_update before update on public.customer_receipts
  for each row execute function private.receipt_before_update();

create table public.installment_payments (
  id             uuid primary key default gen_random_uuid(),
  tenant_id      uuid not null references public.tenants (id),
  receipt_id     uuid not null,
  installment_id uuid not null,
  amount         numeric(18, 2) not null check (amount > 0),
  created_at     timestamptz not null default now(),
  unique (tenant_id, id),
  unique (receipt_id, installment_id),
  foreign key (tenant_id, receipt_id) references public.customer_receipts (tenant_id, id),
  foreign key (tenant_id, installment_id) references public.installments (tenant_id, id)
);
create index installment_payments_installment_idx on public.installment_payments (tenant_id, installment_id);
create trigger installment_payments_no_change before update or delete on public.installment_payments
  for each row execute function private.journal_forbid_change();

-- Paid and remaining per installment, derived (business rule 4). Runs with
-- the caller's rights, so RLS on the underlying tables applies.
create view public.installment_status
with (security_invoker = true)
as
select i.id, i.tenant_id, i.plan_id, p.sale_id, p.customer_id, i.seq, i.due_date, i.amount_due,
       coalesce(paid.amount, 0)::numeric(18, 2) as paid,
       (i.amount_due - coalesce(paid.amount, 0))::numeric(18, 2) as remaining,
       p.status as plan_status
  from public.installments i
  join public.installment_plans p on p.id = i.plan_id
  left join lateral (
    select sum(ip.amount) as amount
      from public.installment_payments ip
      join public.customer_receipts r on r.id = ip.receipt_id
     where ip.installment_id = i.id and r.status = 'POSTED'
  ) paid on true;

-- Scans of papers are documents too (sensitive: deferred_paper.manage).
alter table public.documents drop constraint documents_entity_type_check;
alter table public.documents add constraint documents_entity_type_check
  check (entity_type in ('VEHICLE', 'CUSTOMER', 'SALE', 'SUPPLIER', 'DEFERRED_PAPER'));

-- -----------------------------------------------------------------------------
-- In-app notifications (SPEC §4.17) and the reminder job log (ERD §8).
-- -----------------------------------------------------------------------------
create table public.notifications (
  id          uuid primary key default gen_random_uuid(),
  tenant_id   uuid not null references public.tenants (id),
  user_id     uuid not null,
  kind        text not null,
  params      jsonb not null default '{}',
  entity_type text,
  entity_id   uuid,
  dedupe_key  text not null,
  read_at     timestamptz,
  created_at  timestamptz not null default now(),
  unique (tenant_id, id),
  unique (tenant_id, user_id, dedupe_key)
);
create index notifications_user_idx on public.notifications (tenant_id, user_id, created_at desc);

create table public.reminder_jobs (
  id          uuid primary key default gen_random_uuid(),
  tenant_id   uuid not null references public.tenants (id),
  job_name    text not null,
  run_date    date not null,
  status      text not null default 'RUNNING' check (status in ('RUNNING', 'DONE', 'FAILED')),
  started_at  timestamptz not null default now(),
  finished_at timestamptz,
  stats       jsonb not null default '{}',
  unique (tenant_id, job_name, run_date)
);

-- The worker walks every active tenant, then works inside each tenant's context.
create or replace function private.active_tenant_ids()
returns setof uuid
language sql
stable
security definer
set search_path = ''
as $$
  select id from public.tenants where status = 'ACTIVE' order by id;
$$;

-- -----------------------------------------------------------------------------
-- Security.
-- -----------------------------------------------------------------------------
call private.secure_table('public.installment_plans');
call private.secure_table('public.installments', p_touch => false);
call private.secure_table('public.customer_receipts');
call private.secure_table('public.installment_payments', p_touch => false);
call private.secure_table('public.deferred_papers');
call private.secure_table('public.deferred_paper_events', p_touch => false, p_audit => false);
call private.secure_table('public.notifications', p_touch => false, p_audit => false);
call private.secure_table('public.reminder_jobs', p_touch => false, p_audit => false);
revoke select on public.reminder_jobs from authenticated;

revoke all on public.installment_status from anon, authenticated, service_role, app_api;
grant select on public.installment_status to authenticated, app_api;

do $$
declare
  t text;
begin
  foreach t in array array[
    'installment_plans', 'installments', 'customer_receipts', 'installment_payments', 'deferred_papers',
    'deferred_paper_events', 'notifications', 'reminder_jobs']
  loop
    execute format(
      'create policy %I on public.%I for all to app_api
         using (tenant_id = (select private.current_tenant_id()))
         with check (tenant_id = (select private.current_tenant_id()))',
      t || '_api', t);
  end loop;
end;
$$;

create policy installment_plans_read on public.installment_plans for select to authenticated
  using (tenant_id = any ((select private.tenants_with_permission('installment.view'))::uuid[]));
create policy installments_read on public.installments for select to authenticated
  using (tenant_id = any ((select private.tenants_with_permission('installment.view'))::uuid[]));
create policy customer_receipts_read on public.customer_receipts for select to authenticated
  using (tenant_id = any ((select private.tenants_with_permission('installment.view'))::uuid[]));
create policy installment_payments_read on public.installment_payments for select to authenticated
  using (tenant_id = any ((select private.tenants_with_permission('installment.view'))::uuid[]));
create policy deferred_papers_read on public.deferred_papers for select to authenticated
  using (tenant_id = any ((select private.tenants_with_permission('deferred_paper.manage'))::uuid[]));
create policy deferred_paper_events_read on public.deferred_paper_events for select to authenticated
  using (tenant_id = any ((select private.tenants_with_permission('deferred_paper.manage'))::uuid[]));
create policy notifications_read on public.notifications for select to authenticated
  using (user_id = (select auth.uid()) and tenant_id = any ((select private.my_tenant_ids())::uuid[]));

-- Documents: scans of papers need deferred_paper.manage.
drop policy documents_read on public.documents;
create policy documents_read on public.documents for select to authenticated
  using (
    (sensitivity = 'NORMAL' or tenant_id = any ((select private.tenants_with_permission('vehicle.view_cost'))::uuid[]))
    and ((entity_type = 'VEHICLE' and tenant_id = any ((select private.tenants_with_permission('vehicle.view'))::uuid[]))
      or (entity_type = 'CUSTOMER' and tenant_id = any ((select private.tenants_with_permission('customer.view'))::uuid[]))
      or (entity_type = 'SALE' and tenant_id = any ((select private.tenants_with_permission('sale.view'))::uuid[]))
      or (entity_type = 'SUPPLIER' and tenant_id = any ((select private.tenants_with_permission('supplier.manage'))::uuid[]))
      or (entity_type = 'DEFERRED_PAPER'
          and tenant_id = any ((select private.tenants_with_permission('deferred_paper.manage'))::uuid[])))
  );

revoke execute on all routines in schema private from public, anon, authenticated, service_role;
grant execute on function
  private.current_tenant_id(), private.current_user_id(), private.current_actor_id(),
  private.my_tenant_ids(), private.tenants_with_permission(text), private.is_member(uuid),
  private.has_permission(uuid, text), private.has_any_permission(uuid, text[]),
  private.my_partner_id(uuid), private.is_platform_admin(), private.tenant_writable(uuid),
  private.feature_enabled(uuid, text)
  to authenticated, app_api;
-- The reminder worker (app_api) lists tenants to visit.
grant execute on function private.active_tenant_ids(), private.paper_transition_allowed(text, text, text) to app_api;
