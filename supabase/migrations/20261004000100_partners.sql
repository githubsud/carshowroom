-- =============================================================================
-- Phase 3: partners, ownership history, partner transactions, other income,
-- and partner-funded general expenses (rule 30).
-- Design: SPEC §4.2, docs/ERD.md §3, ACCOUNTING rules 1-5, 28-30, P-01,
-- DECISIONS D-05, D-21, D-62..D-66.
-- =============================================================================

-- -----------------------------------------------------------------------------
-- Partners. The national ID is encrypted by the API (AES-GCM, D-05); the
-- database only stores ciphertext and the last 4 digits for display.
-- A partner is "active" on a date when they hold a share on that date (D-62).
-- -----------------------------------------------------------------------------
create table public.partners (
  id                uuid primary key default gen_random_uuid(),
  tenant_id         uuid not null references public.tenants (id),
  name_ar           text not null check (length(btrim(name_ar)) > 0),
  name_en           text,
  phone             text,
  national_id_enc   text,
  national_id_last4 text check (national_id_last4 ~ '^[0-9A-Za-z]{1,4}$'),
  notes             text,
  archived_at       timestamptz,
  created_at        timestamptz not null default now(),
  created_by        uuid,
  updated_at        timestamptz not null default now(),
  updated_by        uuid,
  unique (tenant_id, id),
  check ((national_id_enc is null) = (national_id_last4 is null))
);

-- Membership <-> partner link (Partner role sees their own statement).
alter table public.memberships
  add constraint memberships_partner_fk
  foreign key (tenant_id, partner_id) references public.partners (tenant_id, id);
create unique index memberships_one_user_per_partner_idx on public.memberships (tenant_id, partner_id)
  where partner_id is not null;

-- Journal subledger: partner lines now reference real partners.
alter table public.journal_lines
  add constraint journal_lines_partner_fk
  foreign key (tenant_id, partner_id) references public.partners (tenant_id, id);

-- -----------------------------------------------------------------------------
-- Ownership history (SPEC §4.2): effective-dated, never overwritten. Every
-- change is a batch with one change_batch_id; at commit, active shares must
-- total exactly 100.0000 on every date that has shares (D-21).
-- -----------------------------------------------------------------------------
create table public.partner_share_history (
  id              uuid primary key default gen_random_uuid(),
  tenant_id       uuid not null references public.tenants (id),
  partner_id      uuid not null,
  percentage      numeric(9, 4) not null check (percentage > 0 and percentage <= 100),
  effective_from  date not null,
  effective_to    date,
  change_batch_id uuid not null,
  created_at      timestamptz not null default now(),
  created_by      uuid,
  updated_at      timestamptz not null default now(),
  updated_by      uuid,
  unique (tenant_id, id),
  foreign key (tenant_id, partner_id) references public.partners (tenant_id, id),
  check (effective_to is null or effective_to >= effective_from),
  -- One share per partner per day.
  constraint partner_share_no_overlap exclude using gist (
    tenant_id with =,
    partner_id with =,
    daterange(effective_from, effective_to, '[]') with &&
  )
);

create index partner_share_history_dates_idx on public.partner_share_history (tenant_id, effective_from, effective_to);

create or replace function private.check_partner_shares()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_day   date;
  v_total numeric;
begin
  select d.day, sum(s.percentage)
    into v_day, v_total
    from (select distinct effective_from as day from public.partner_share_history where tenant_id = new.tenant_id) d
    join public.partner_share_history s
      on s.tenant_id = new.tenant_id
     and s.effective_from <= d.day
     and (s.effective_to is null or s.effective_to >= d.day)
   group by d.day
  having sum(s.percentage) <> 100
   order by d.day
   limit 1;

  if v_day is not null then
    raise exception 'partner shares total % on %, not 100', v_total, v_day
      using errcode = 'SR010', detail = format('%s|%s', v_day, v_total);
  end if;
  return null;
end;
$$;

create constraint trigger partner_shares_total_100
  after insert or update on public.partner_share_history
  deferrable initially deferred
  for each row execute function private.check_partner_shares();

-- History is append-only: rows are never deleted, and only effective_to of an
-- open row may be set (closing it when a new batch starts).
create or replace function private.partner_share_before_update()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  if old.effective_to is null and new.effective_to is not null
     and (to_jsonb(new) - array['effective_to', 'updated_at', 'updated_by'])
       = (to_jsonb(old) - array['effective_to', 'updated_at', 'updated_by']) then
    return new;
  end if;
  raise exception 'ownership history cannot be changed; record a new share change' using errcode = 'SR003';
end;
$$;

create trigger partner_share_history_before_update
  before update on public.partner_share_history
  for each row execute function private.partner_share_before_update();

create trigger partner_share_history_no_delete
  before delete on public.partner_share_history
  for each row execute function private.journal_forbid_change();

-- -----------------------------------------------------------------------------
-- Partner transactions (rules 1-5, 28, 29). One table, one type per rule.
-- -----------------------------------------------------------------------------
create table public.partner_transactions (
  id                uuid primary key default gen_random_uuid(),
  tenant_id         uuid not null references public.tenants (id),
  partner_id        uuid not null,
  type              text not null check (type in (
                      'CONTRIBUTION', 'CAPITAL_WITHDRAWAL', 'DRAWING',
                      'LOAN_TO_PARTNER', 'LOAN_TO_PARTNER_REPAYMENT',
                      'LOAN_FROM_PARTNER', 'LOAN_FROM_PARTNER_REPAYMENT')),
  txn_date          date not null,
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
  foreign key (tenant_id, partner_id) references public.partners (tenant_id, id),
  foreign key (tenant_id, cash_account_id) references public.cash_accounts (tenant_id, id),
  foreign key (tenant_id, journal_entry_id) references public.journal_entries (tenant_id, id),
  foreign key (tenant_id, reversal_entry_id) references public.journal_entries (tenant_id, id),
  check ((status = 'REVERSED') = (reversal_entry_id is not null))
);

create index partner_transactions_partner_idx on public.partner_transactions (tenant_id, partner_id, txn_date);

create trigger partner_transactions_before_update
  before update on public.partner_transactions
  for each row execute function private.posted_document_before_update();

-- -----------------------------------------------------------------------------
-- Other income (P-01, approved 2026-10-02): Dr cash/bank / Cr 4900.
-- -----------------------------------------------------------------------------
create table public.other_incomes (
  id                uuid primary key default gen_random_uuid(),
  tenant_id         uuid not null references public.tenants (id),
  income_date       date not null,
  amount            numeric(18, 2) not null check (amount > 0),
  description       text not null check (length(btrim(description)) > 0),
  cash_account_id   uuid not null,
  status            text not null default 'POSTED' check (status in ('POSTED', 'REVERSED')),
  journal_entry_id  uuid not null,
  reversal_entry_id uuid,
  created_at        timestamptz not null default now(),
  created_by        uuid,
  updated_at        timestamptz not null default now(),
  updated_by        uuid,
  unique (tenant_id, id),
  foreign key (tenant_id, cash_account_id) references public.cash_accounts (tenant_id, id),
  foreign key (tenant_id, journal_entry_id) references public.journal_entries (tenant_id, id),
  foreign key (tenant_id, reversal_entry_id) references public.journal_entries (tenant_id, id),
  check ((status = 'REVERSED') = (reversal_entry_id is not null))
);

create index other_incomes_date_idx on public.other_incomes (tenant_id, income_date);

create trigger other_incomes_before_update
  before update on public.other_incomes
  for each row execute function private.posted_document_before_update();

-- -----------------------------------------------------------------------------
-- General expenses paid personally by a partner (rule 30): no cash account;
-- credited to the partner's current account or recorded as a loan from them.
-- -----------------------------------------------------------------------------
alter table public.general_expenses
  alter column cash_account_id drop not null,
  add column paid_by_partner_id uuid,
  add column partner_funding_mode text check (partner_funding_mode in ('CURRENT_ACCOUNT', 'LOAN')),
  add constraint general_expenses_partner_fk
    foreign key (tenant_id, paid_by_partner_id) references public.partners (tenant_id, id),
  add constraint general_expenses_one_funding check (
    (cash_account_id is not null and paid_by_partner_id is null and partner_funding_mode is null)
    or (cash_account_id is null and paid_by_partner_id is not null and partner_funding_mode is not null)
  );

-- -----------------------------------------------------------------------------
-- Security.
-- -----------------------------------------------------------------------------
call private.secure_table('public.partners');
call private.secure_table('public.partner_share_history');
call private.secure_table('public.partner_transactions');
call private.secure_table('public.other_incomes');

-- Partners: everyone with partner.view_all, and a partner their own row.
create policy partners_read on public.partners
  for select to authenticated
  using (tenant_id = any ((select private.tenants_with_permission('partner.view_all'))::uuid[])
      or (tenant_id = any ((select private.tenants_with_permission('partner.view_own'))::uuid[])
          and id = (select private.my_partner_id(tenant_id))));
create policy partners_api on public.partners
  for all to app_api
  using (tenant_id = (select private.current_tenant_id()))
  with check (tenant_id = (select private.current_tenant_id()));

create policy partner_share_history_read on public.partner_share_history
  for select to authenticated
  using (tenant_id = any ((select private.tenants_with_permission('partner.view_all'))::uuid[])
      or (tenant_id = any ((select private.tenants_with_permission('partner.view_own'))::uuid[])
          and partner_id = (select private.my_partner_id(tenant_id))));
create policy partner_share_history_api on public.partner_share_history
  for all to app_api
  using (tenant_id = (select private.current_tenant_id()))
  with check (tenant_id = (select private.current_tenant_id()));

create policy partner_transactions_read on public.partner_transactions
  for select to authenticated
  using (tenant_id = any ((select private.tenants_with_permission('partner.view_all'))::uuid[])
      or (tenant_id = any ((select private.tenants_with_permission('partner.view_own'))::uuid[])
          and partner_id = (select private.my_partner_id(tenant_id))));
create policy partner_transactions_api on public.partner_transactions
  for all to app_api
  using (tenant_id = (select private.current_tenant_id()))
  with check (tenant_id = (select private.current_tenant_id()));

create policy other_incomes_read on public.other_incomes
  for select to authenticated
  using (tenant_id = any ((select private.tenants_with_permission('cash.view'))::uuid[]));
create policy other_incomes_api on public.other_incomes
  for all to app_api
  using (tenant_id = (select private.current_tenant_id()))
  with check (tenant_id = (select private.current_tenant_id()));

revoke execute on all routines in schema private from public, anon, authenticated, service_role;
grant execute on function
  private.current_tenant_id(), private.current_user_id(), private.current_actor_id(),
  private.my_tenant_ids(), private.tenants_with_permission(text), private.is_member(uuid),
  private.has_permission(uuid, text), private.has_any_permission(uuid, text[]),
  private.my_partner_id(uuid), private.is_platform_admin(), private.tenant_writable(uuid),
  private.feature_enabled(uuid, text)
  to authenticated, app_api;
