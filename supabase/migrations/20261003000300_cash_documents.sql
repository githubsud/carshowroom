-- =============================================================================
-- Phase 2: money-moving documents (general expenses, cash/bank transfers) and
-- idempotency keys. Documents are written only by the API, inside the same
-- transaction as their journal entry. After posting, only the reversal link
-- may change (SPEC §3.3: financial records are never updated after posting).
-- =============================================================================

create table public.general_expenses (
  id                uuid primary key default gen_random_uuid(),
  tenant_id         uuid not null references public.tenants (id),
  expense_date      date not null,
  category_id       uuid not null,
  amount            numeric(18, 2) not null check (amount > 0),
  description       text,
  cash_account_id   uuid not null,
  status            text not null default 'POSTED' check (status in ('POSTED', 'REVERSED')),
  journal_entry_id  uuid not null,
  reversal_entry_id uuid,
  created_at        timestamptz not null default now(),
  created_by        uuid,
  updated_at        timestamptz not null default now(),
  updated_by        uuid,
  unique (tenant_id, id),
  foreign key (tenant_id, category_id) references public.expense_categories (tenant_id, id),
  foreign key (tenant_id, cash_account_id) references public.cash_accounts (tenant_id, id),
  foreign key (tenant_id, journal_entry_id) references public.journal_entries (tenant_id, id),
  foreign key (tenant_id, reversal_entry_id) references public.journal_entries (tenant_id, id),
  check ((status = 'REVERSED') = (reversal_entry_id is not null))
);

create index general_expenses_date_idx on public.general_expenses (tenant_id, expense_date);
create index general_expenses_category_idx on public.general_expenses (tenant_id, category_id, expense_date);

create table public.transfers (
  id                   uuid primary key default gen_random_uuid(),
  tenant_id            uuid not null references public.tenants (id),
  transfer_date        date not null,
  from_cash_account_id uuid not null,
  to_cash_account_id   uuid not null,
  amount               numeric(18, 2) not null check (amount > 0),
  notes                text,
  status               text not null default 'POSTED' check (status in ('POSTED', 'REVERSED')),
  journal_entry_id     uuid not null,
  reversal_entry_id    uuid,
  created_at           timestamptz not null default now(),
  created_by           uuid,
  updated_at           timestamptz not null default now(),
  updated_by           uuid,
  unique (tenant_id, id),
  foreign key (tenant_id, from_cash_account_id) references public.cash_accounts (tenant_id, id),
  foreign key (tenant_id, to_cash_account_id) references public.cash_accounts (tenant_id, id),
  foreign key (tenant_id, journal_entry_id) references public.journal_entries (tenant_id, id),
  foreign key (tenant_id, reversal_entry_id) references public.journal_entries (tenant_id, id),
  check (from_cash_account_id <> to_cash_account_id),
  check ((status = 'REVERSED') = (reversal_entry_id is not null))
);

create index transfers_date_idx on public.transfers (tenant_id, transfer_date);

-- After posting, a document only moves POSTED -> REVERSED with its reversal entry.
create or replace function private.posted_document_before_update()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  if old.status = 'POSTED' and new.status = 'REVERSED' and new.reversal_entry_id is not null
     and (to_jsonb(new) - array['status', 'reversal_entry_id', 'updated_at', 'updated_by'])
       = (to_jsonb(old) - array['status', 'reversal_entry_id', 'updated_at', 'updated_by']) then
    return new;
  end if;
  raise exception 'posted financial records cannot be changed; reverse them instead'
    using errcode = 'SR003';
end;
$$;

create trigger general_expenses_before_update
  before update on public.general_expenses
  for each row execute function private.posted_document_before_update();
create trigger transfers_before_update
  before update on public.transfers
  for each row execute function private.posted_document_before_update();

-- -----------------------------------------------------------------------------
-- Idempotency (SPEC §3.3, D-17). The row is written in the same transaction as
-- the operation: if the operation rolls back, so does the key, and the client
-- may retry. A concurrent duplicate waits on the primary key, then replays.
-- -----------------------------------------------------------------------------
create table public.idempotency_keys (
  tenant_id     uuid not null references public.tenants (id),
  key           text not null check (length(key) between 8 and 128),
  user_id       uuid not null,
  endpoint      text not null,
  request_hash  text not null,
  response_code smallint not null,
  response_body jsonb not null,
  created_at    timestamptz not null default now(),
  primary key (tenant_id, key)
);

create index idempotency_keys_created_idx on public.idempotency_keys (created_at);

-- -----------------------------------------------------------------------------
-- Security: browser may read documents with cash.view; writes only via the API.
-- -----------------------------------------------------------------------------
call private.secure_table('public.general_expenses');
call private.secure_table('public.transfers');
call private.secure_table('public.idempotency_keys', p_touch => false, p_audit => false);
revoke select on table public.idempotency_keys from authenticated;

create policy general_expenses_read on public.general_expenses
  for select to authenticated
  using (tenant_id = any ((select private.tenants_with_permission('cash.view'))::uuid[]));
create policy general_expenses_api on public.general_expenses
  for all to app_api
  using (tenant_id = (select private.current_tenant_id()))
  with check (tenant_id = (select private.current_tenant_id()));

create policy transfers_read on public.transfers
  for select to authenticated
  using (tenant_id = any ((select private.tenants_with_permission('cash.view'))::uuid[]));
create policy transfers_api on public.transfers
  for all to app_api
  using (tenant_id = (select private.current_tenant_id()))
  with check (tenant_id = (select private.current_tenant_id()));

create policy idempotency_keys_api on public.idempotency_keys
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
