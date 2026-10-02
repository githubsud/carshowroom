-- =============================================================================
-- Phase 2: the ledger. Accounting periods, journal entries and lines, and the
-- integrity rules of SPEC §5 enforced in the database:
--   * each line has exactly one of debit/credit > 0           (check constraint)
--   * each entry has >= 2 lines and sum(debit) = sum(credit)    (deferred trigger, at commit)
--   * entries and lines are immutable; only reversed_by_id is set, once, by
--     reverse_journal_entry()                                   (triggers)
--   * posting date must be in an OPEN period                    (trigger)
--   * entry_no is sequential per tenant without gaps            (counter row in the same transaction)
--   * post_journal_entry() / reverse_journal_entry() are the only way in
--     (no INSERT/UPDATE/DELETE grant on journal tables for any client role)
--
-- Custom SQLSTATEs, mapped to API error codes in app/services/posting/engine.py:
--   SR001 PERIOD_LOCKED        SR002 ENTRY_UNBALANCED      SR003 LEDGER_IMMUTABLE
--   SR004 ENTRY_ALREADY_REVERSED  SR005 ACCOUNT_NOT_POSTABLE  SR006 SUBLEDGER_MISMATCH
--   SR007 INVALID_ENTRY        SR008 ENTRY_IS_REVERSAL
-- =============================================================================

-- -----------------------------------------------------------------------------
-- Accounting periods: one row per tenant and month, created on first use.
-- -----------------------------------------------------------------------------
create table public.accounting_periods (
  id          uuid primary key default gen_random_uuid(),
  tenant_id   uuid not null references public.tenants (id),
  month       date not null check (extract(day from month) = 1),
  status      text not null default 'OPEN' check (status in ('OPEN', 'LOCKED')),
  locked_at   timestamptz,
  locked_by   uuid,
  created_at  timestamptz not null default now(),
  created_by  uuid,
  updated_at  timestamptz not null default now(),
  updated_by  uuid,
  unique (tenant_id, id),
  unique (tenant_id, month)
);

-- -----------------------------------------------------------------------------
-- Journal entries and lines.
-- -----------------------------------------------------------------------------
create table public.journal_entries (
  id              uuid primary key default gen_random_uuid(),
  tenant_id       uuid not null references public.tenants (id),
  entry_no        bigint not null check (entry_no > 0),
  entry_date      date not null,
  description     text not null check (length(btrim(description)) > 0),
  source_type     text not null check (source_type ~ '^[A-Z_]+$'),
  source_id       uuid,
  status          text not null default 'POSTED' check (status = 'POSTED'),
  reversal_of_id  uuid,
  reversed_by_id  uuid,
  reversal_reason text,
  period_id       uuid not null,
  is_opening      boolean not null default false,
  is_closing      boolean not null default false,
  created_by      uuid,
  created_at      timestamptz not null default now(),
  posted_at       timestamptz not null default now(),
  unique (tenant_id, id),
  unique (tenant_id, entry_no),
  foreign key (tenant_id, period_id) references public.accounting_periods (tenant_id, id),
  foreign key (tenant_id, reversal_of_id) references public.journal_entries (tenant_id, id),
  foreign key (tenant_id, reversed_by_id) references public.journal_entries (tenant_id, id),
  check ((reversal_of_id is null) = (reversal_reason is null))
);

-- An entry can be reversed once.
create unique index journal_entries_one_reversal_idx on public.journal_entries (tenant_id, reversal_of_id)
  where reversal_of_id is not null;
create index journal_entries_date_idx on public.journal_entries (tenant_id, entry_date);
create index journal_entries_source_idx on public.journal_entries (tenant_id, source_type, source_id);

-- Subledger columns for partners, customers, vehicles, consignors, external
-- showrooms and suppliers get their composite foreign keys when those tables
-- arrive (Phases 3, 4, 6).
create table public.journal_lines (
  id                   uuid primary key default gen_random_uuid(),
  tenant_id            uuid not null references public.tenants (id),
  journal_entry_id     uuid not null,
  line_no              smallint not null check (line_no > 0),
  ledger_account_id    uuid not null,
  debit                numeric(18, 2) not null default 0,
  credit               numeric(18, 2) not null default 0,
  entry_date           date not null,
  cash_account_id      uuid,
  partner_id           uuid,
  customer_id          uuid,
  vehicle_id           uuid,
  consignor_id         uuid,
  external_showroom_id uuid,
  supplier_id          uuid,
  memo                 text,
  created_at           timestamptz not null default now(),
  unique (tenant_id, id),
  unique (journal_entry_id, line_no),
  foreign key (tenant_id, journal_entry_id) references public.journal_entries (tenant_id, id),
  foreign key (tenant_id, ledger_account_id) references public.ledger_accounts (tenant_id, id),
  foreign key (tenant_id, cash_account_id) references public.cash_accounts (tenant_id, id),
  -- Exactly one side, positive (SPEC §5).
  constraint journal_lines_one_side check (
    debit >= 0 and credit >= 0 and ((debit > 0 and credit = 0) or (credit > 0 and debit = 0))
  )
);

-- SPEC §11: lines indexed by account, partner, vehicle, customer and date.
create index journal_lines_account_idx on public.journal_lines (tenant_id, ledger_account_id, entry_date)
  include (debit, credit);
create index journal_lines_cash_idx on public.journal_lines (tenant_id, cash_account_id, entry_date)
  include (debit, credit) where cash_account_id is not null;
create index journal_lines_partner_idx on public.journal_lines (tenant_id, partner_id, entry_date)
  where partner_id is not null;
create index journal_lines_customer_idx on public.journal_lines (tenant_id, customer_id, entry_date)
  where customer_id is not null;
create index journal_lines_vehicle_idx on public.journal_lines (tenant_id, vehicle_id)
  where vehicle_id is not null;
create index journal_lines_consignor_idx on public.journal_lines (tenant_id, consignor_id)
  where consignor_id is not null;
create index journal_lines_external_idx on public.journal_lines (tenant_id, external_showroom_id)
  where external_showroom_id is not null;
create index journal_lines_supplier_idx on public.journal_lines (tenant_id, supplier_id)
  where supplier_id is not null;
create index journal_lines_entry_idx on public.journal_lines (journal_entry_id);

-- -----------------------------------------------------------------------------
-- Entry header: open period, stamping.
-- -----------------------------------------------------------------------------
create or replace function private.journal_entry_before_insert()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_month  date := date_trunc('month', new.entry_date)::date;
  v_period public.accounting_periods;
begin
  insert into public.accounting_periods (tenant_id, month)
  values (new.tenant_id, v_month)
  on conflict (tenant_id, month) do nothing;

  -- FOR SHARE: a concurrent lock of this month waits for us (and vice versa).
  select * into v_period
    from public.accounting_periods
   where tenant_id = new.tenant_id and month = v_month
   for share;

  if v_period.status = 'LOCKED' then
    raise exception 'period % is locked', to_char(v_month, 'YYYY-MM')
      using errcode = 'SR001', detail = to_char(v_month, 'YYYY-MM');
  end if;

  new.period_id := v_period.id;
  new.status := 'POSTED';
  new.created_at := now();
  new.posted_at := now();
  new.reversed_by_id := null;
  return new;
end;
$$;

create trigger journal_entries_before_insert
  before insert on public.journal_entries
  for each row execute function private.journal_entry_before_insert();

-- -----------------------------------------------------------------------------
-- Lines: same-transaction only, postable account, subledger consistency.
-- -----------------------------------------------------------------------------
create or replace function private.journal_line_before_insert()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_entry   public.journal_entries;
  v_account public.ledger_accounts;
  v_cash    public.cash_accounts;
begin
  select * into v_entry from public.journal_entries
   where id = new.journal_entry_id and tenant_id = new.tenant_id;

  -- Lines can only be added in the transaction that created the entry:
  -- a posted entry is never extended later.
  if v_entry.posted_at is distinct from now() then
    raise exception 'journal entry % is already posted', v_entry.entry_no using errcode = 'SR003';
  end if;
  new.entry_date := v_entry.entry_date;
  new.created_at := now();

  select * into v_account from public.ledger_accounts
   where id = new.ledger_account_id and tenant_id = new.tenant_id;
  if not v_account.is_postable or v_account.archived_at is not null then
    raise exception 'account % is not postable', v_account.code using errcode = 'SR005', detail = v_account.code;
  end if;

  -- The subledger id required by the account must be present, and a cash
  -- account id may only appear on that cash account's own ledger account.
  if v_account.subledger = 'CASH_ACCOUNT' or new.cash_account_id is not null then
    select * into v_cash from public.cash_accounts
     where id = new.cash_account_id and tenant_id = new.tenant_id;
    if v_cash.id is null or v_cash.ledger_account_id <> new.ledger_account_id then
      raise exception 'cash account does not match ledger account %', v_account.code
        using errcode = 'SR006', detail = v_account.code;
    end if;
  end if;

  if (v_account.subledger = 'PARTNER' and new.partner_id is null)
     or (v_account.subledger = 'CUSTOMER' and new.customer_id is null)
     or (v_account.subledger = 'VEHICLE' and new.vehicle_id is null)
     or (v_account.subledger = 'CONSIGNOR' and new.consignor_id is null)
     or (v_account.subledger = 'EXTERNAL_SHOWROOM' and new.external_showroom_id is null)
     or (v_account.subledger = 'SUPPLIER' and new.supplier_id is null) then
    raise exception 'account % requires a % subledger id', v_account.code, lower(v_account.subledger)
      using errcode = 'SR006', detail = v_account.code;
  end if;
  return new;
end;
$$;

create trigger journal_lines_before_insert
  before insert on public.journal_lines
  for each row execute function private.journal_line_before_insert();

-- -----------------------------------------------------------------------------
-- Balance check at commit (deferred), so a bypassed application check still
-- cannot leave an unbalanced or single-line entry behind.
-- -----------------------------------------------------------------------------
create or replace function private.journal_entry_check_balance()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_lines  integer;
  v_debit  numeric;
  v_credit numeric;
begin
  select count(*), coalesce(sum(debit), 0), coalesce(sum(credit), 0)
    into v_lines, v_debit, v_credit
    from public.journal_lines
   where journal_entry_id = new.id;

  if v_lines < 2 or v_debit <> v_credit or v_debit = 0 then
    raise exception 'journal entry % is unbalanced (lines %, debit %, credit %)',
      new.entry_no, v_lines, v_debit, v_credit
      using errcode = 'SR002';
  end if;
  return null;
end;
$$;

create constraint trigger journal_entries_balanced
  after insert on public.journal_entries
  deferrable initially deferred
  for each row execute function private.journal_entry_check_balance();

-- -----------------------------------------------------------------------------
-- Immutability.
-- -----------------------------------------------------------------------------
create or replace function private.journal_forbid_change()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  raise exception 'posted ledger records cannot be changed; reverse the entry instead'
    using errcode = 'SR003';
end;
$$;

create or replace function private.journal_entry_before_update()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  -- The single permitted change: reverse_journal_entry() links the reversal.
  if old.reversed_by_id is null
     and new.reversed_by_id is not null
     and current_setting('app.ledger_reversal_of', true) = old.id::text
     and (to_jsonb(new) - 'reversed_by_id') = (to_jsonb(old) - 'reversed_by_id') then
    return new;
  end if;
  raise exception 'posted ledger records cannot be changed; reverse the entry instead'
    using errcode = 'SR003';
end;
$$;

create trigger journal_entries_before_update
  before update on public.journal_entries
  for each row execute function private.journal_entry_before_update();
create trigger journal_entries_no_delete
  before delete on public.journal_entries
  for each row execute function private.journal_forbid_change();
create trigger journal_entries_no_truncate
  before truncate on public.journal_entries
  for each statement execute function private.journal_forbid_change();
create trigger journal_lines_no_change
  before update or delete on public.journal_lines
  for each row execute function private.journal_forbid_change();
create trigger journal_lines_no_truncate
  before truncate on public.journal_lines
  for each statement execute function private.journal_forbid_change();

-- -----------------------------------------------------------------------------
-- The only way in: post_journal_entry(entry jsonb).
--
--   { "entry_date": "2026-10-02", "description": "...", "source_type": "GENERAL_EXPENSE",
--     "source_id": "<uuid>" | null, "is_opening": false, "is_closing": false,
--     "lines": [ { "ledger_account_id": "<uuid>", "debit": "100.00", "credit": "0",
--                  "cash_account_id": null, "partner_id": null, ..., "memo": null }, ... ] }
--
-- The tenant is always the request's app.tenant_id, never a value in the payload.
-- -----------------------------------------------------------------------------
create or replace function private.insert_journal_entry(
  p_entry          jsonb,
  p_reversal_of_id uuid default null,
  p_reason         text default null
)
returns table (journal_entry_id uuid, entry_no bigint)
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_tenant uuid := private.current_tenant_id();
  v_id     uuid := gen_random_uuid();
  v_no     bigint;
  v_line   jsonb;
  v_index  integer := 0;
  v_debit  numeric;
  v_credit numeric;
begin
  if v_tenant is null then
    raise exception 'tenant context (app.tenant_id) is required' using errcode = 'SR007';
  end if;
  if jsonb_typeof(p_entry -> 'lines') is distinct from 'array' or jsonb_array_length(p_entry -> 'lines') < 2 then
    raise exception 'a journal entry needs at least two lines' using errcode = 'SR002';
  end if;

  -- Gapless numbering: the counter row stays locked until commit, and rolls
  -- back with the transaction.
  insert into public.tenant_counters as c (tenant_id, counter_key, last_value)
  values (v_tenant, 'journal_entry', 1)
  on conflict (tenant_id, counter_key) do update set last_value = c.last_value + 1
  returning c.last_value into v_no;

  insert into public.journal_entries (
    id, tenant_id, entry_no, entry_date, description, source_type, source_id,
    reversal_of_id, reversal_reason, is_opening, is_closing, created_by, period_id
  ) values (
    v_id, v_tenant, v_no,
    (p_entry ->> 'entry_date')::date,
    p_entry ->> 'description',
    p_entry ->> 'source_type',
    nullif(p_entry ->> 'source_id', '')::uuid,
    p_reversal_of_id,
    p_reason,
    coalesce((p_entry ->> 'is_opening')::boolean, false),
    coalesce((p_entry ->> 'is_closing')::boolean, false),
    private.current_actor_id(),
    -- Placeholder, replaced by the before-insert trigger with the real period.
    '00000000-0000-0000-0000-000000000000'
  );

  for v_line in select value from jsonb_array_elements(p_entry -> 'lines') loop
    v_index := v_index + 1;
    v_debit := coalesce(nullif(v_line ->> 'debit', '')::numeric, 0);
    v_credit := coalesce(nullif(v_line ->> 'credit', '')::numeric, 0);
    -- Never round silently: amounts must already have at most 2 decimals.
    if v_debit <> round(v_debit, 2) or v_credit <> round(v_credit, 2) then
      raise exception 'line % has more than 2 decimals', v_index using errcode = 'SR007';
    end if;

    insert into public.journal_lines (
      tenant_id, journal_entry_id, line_no, ledger_account_id, debit, credit, entry_date,
      cash_account_id, partner_id, customer_id, vehicle_id, consignor_id,
      external_showroom_id, supplier_id, memo
    ) values (
      v_tenant, v_id, v_index,
      (v_line ->> 'ledger_account_id')::uuid,
      v_debit, v_credit,
      (p_entry ->> 'entry_date')::date,
      nullif(v_line ->> 'cash_account_id', '')::uuid,
      nullif(v_line ->> 'partner_id', '')::uuid,
      nullif(v_line ->> 'customer_id', '')::uuid,
      nullif(v_line ->> 'vehicle_id', '')::uuid,
      nullif(v_line ->> 'consignor_id', '')::uuid,
      nullif(v_line ->> 'external_showroom_id', '')::uuid,
      nullif(v_line ->> 'supplier_id', '')::uuid,
      nullif(v_line ->> 'memo', '')
    );
  end loop;

  return query select v_id, v_no;
end;
$$;

create or replace function private.post_journal_entry(p_entry jsonb)
returns table (journal_entry_id uuid, entry_no bigint)
language plpgsql
security definer
set search_path = ''
as $$
begin
  if p_entry ? 'reversal_of_id' then
    raise exception 'use reverse_journal_entry() for reversals' using errcode = 'SR007';
  end if;
  return query select * from private.insert_journal_entry(p_entry);
end;
$$;

-- -----------------------------------------------------------------------------
-- reverse_journal_entry(): rule 24. Exact mirror, linked both ways, reason
-- mandatory, dated p_date (must be in an open period).
-- -----------------------------------------------------------------------------
create or replace function private.reverse_journal_entry(p_entry_id uuid, p_reason text, p_date date)
returns table (journal_entry_id uuid, entry_no bigint)
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_tenant   uuid := private.current_tenant_id();
  v_original public.journal_entries;
  v_lines    jsonb;
  v_new_id   uuid;
  v_new_no   bigint;
begin
  if v_tenant is null then
    raise exception 'tenant context (app.tenant_id) is required' using errcode = 'SR007';
  end if;
  if p_reason is null or length(btrim(p_reason)) = 0 then
    raise exception 'a reversal needs a reason' using errcode = 'SR007';
  end if;

  select * into v_original from public.journal_entries
   where id = p_entry_id and tenant_id = v_tenant
   for update;
  if v_original.id is null then
    raise exception 'journal entry not found' using errcode = 'SR007';
  end if;
  if v_original.reversed_by_id is not null then
    raise exception 'journal entry % is already reversed', v_original.entry_no using errcode = 'SR004';
  end if;
  if v_original.reversal_of_id is not null then
    raise exception 'journal entry % is itself a reversal', v_original.entry_no using errcode = 'SR008';
  end if;

  select jsonb_agg(
           jsonb_build_object(
             'ledger_account_id', l.ledger_account_id,
             'debit', l.credit,
             'credit', l.debit,
             'cash_account_id', l.cash_account_id,
             'partner_id', l.partner_id,
             'customer_id', l.customer_id,
             'vehicle_id', l.vehicle_id,
             'consignor_id', l.consignor_id,
             'external_showroom_id', l.external_showroom_id,
             'supplier_id', l.supplier_id,
             'memo', l.memo
           ) order by l.line_no)
    into v_lines
    from public.journal_lines l
   where l.journal_entry_id = v_original.id;

  select r.journal_entry_id, r.entry_no into v_new_id, v_new_no
    from private.insert_journal_entry(
      jsonb_build_object(
        'entry_date', p_date,
        'description', v_original.description,
        'source_type', v_original.source_type,
        'source_id', v_original.source_id,
        'is_opening', v_original.is_opening,
        'is_closing', v_original.is_closing,
        'lines', v_lines
      ),
      v_original.id,
      btrim(p_reason)
    ) r;

  perform set_config('app.ledger_reversal_of', v_original.id::text, true);
  update public.journal_entries set reversed_by_id = v_new_id where id = v_original.id;
  perform set_config('app.ledger_reversal_of', '', true);

  return query select v_new_id, v_new_no;
end;
$$;

-- -----------------------------------------------------------------------------
-- Security. Journal tables: read-only for every client role (writes only via
-- the SECURITY DEFINER functions above). The ledger is its own audit trail
-- (created_by, immutable rows), so no row-change audit triggers here.
-- -----------------------------------------------------------------------------
call private.secure_table('public.accounting_periods');
call private.secure_table('public.journal_entries', p_touch => false, p_audit => false);
call private.secure_table('public.journal_lines', p_touch => false, p_audit => false);
revoke insert, update on table public.journal_entries, public.journal_lines from app_api;

create policy accounting_periods_read on public.accounting_periods
  for select to authenticated
  using (tenant_id = any ((select private.tenants_with_permission('cash.view'))::uuid[])
      or tenant_id = any ((select private.tenants_with_permission('journal.view'))::uuid[]));

create policy accounting_periods_api on public.accounting_periods
  for all to app_api
  using (tenant_id = (select private.current_tenant_id()))
  with check (tenant_id = (select private.current_tenant_id()));

create policy journal_entries_read on public.journal_entries
  for select to authenticated
  using (tenant_id = any ((select private.tenants_with_permission('journal.view'))::uuid[])
      or tenant_id = any ((select private.tenants_with_permission('cash.view'))::uuid[]));

create policy journal_entries_api on public.journal_entries
  for select to app_api
  using (tenant_id = (select private.current_tenant_id()));

create policy journal_lines_read on public.journal_lines
  for select to authenticated
  using (tenant_id = any ((select private.tenants_with_permission('journal.view'))::uuid[])
      or tenant_id = any ((select private.tenants_with_permission('cash.view'))::uuid[])
      -- A partner sees the lines of their own partner subledger (Phase 3).
      or (partner_id is not null
          and tenant_id = any ((select private.tenants_with_permission('partner.view_own'))::uuid[])
          and partner_id = (select private.my_partner_id(tenant_id))));

create policy journal_lines_api on public.journal_lines
  for select to app_api
  using (tenant_id = (select private.current_tenant_id()));

revoke execute on all routines in schema private from public, anon, authenticated, service_role;
grant execute on function
  private.current_tenant_id(), private.current_user_id(), private.current_actor_id(),
  private.my_tenant_ids(), private.tenants_with_permission(text), private.is_member(uuid),
  private.has_permission(uuid, text), private.has_any_permission(uuid, text[]),
  private.my_partner_id(uuid), private.is_platform_admin(), private.tenant_writable(uuid),
  private.feature_enabled(uuid, text)
  to authenticated, app_api;
grant execute on function
  private.post_journal_entry(jsonb),
  private.reverse_journal_entry(uuid, text, date)
  to app_api;
