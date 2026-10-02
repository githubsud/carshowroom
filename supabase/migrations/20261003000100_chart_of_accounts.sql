-- =============================================================================
-- Phase 2: chart of accounts, cash accounts, expense categories, payment methods.
-- Design: docs/ACCOUNTING.md §2, docs/ERD.md §7, DECISIONS D-26, D-27, D-40, D-41.
-- =============================================================================

-- -----------------------------------------------------------------------------
-- Chart of accounts template (reference data, SPEC §6). Copied into every
-- tenant on creation; tenants then add sub-accounts (cash boxes, banks,
-- general expense categories).
-- -----------------------------------------------------------------------------
create table public.coa_template (
  code        text primary key check (code ~ '^[0-9]{4}$'),
  parent_code text references public.coa_template (code),
  name_ar     text not null,
  name_en     text not null,
  type        text not null check (type in ('ASSET', 'LIABILITY', 'EQUITY', 'INCOME', 'EXPENSE')),
  normal_side text not null check (normal_side in ('DEBIT', 'CREDIT')),
  is_postable boolean not null,
  subledger   text not null default 'NONE'
              check (subledger in ('NONE', 'PARTNER', 'CUSTOMER', 'VEHICLE', 'CONSIGNOR',
                                   'EXTERNAL_SHOWROOM', 'SUPPLIER', 'CASH_ACCOUNT')),
  -- Stable key the posting rules use; codes may be renumbered per country later.
  system_key  text unique
);

insert into public.coa_template (code, parent_code, name_ar, name_en, type, normal_side, is_postable, subledger, system_key) values
  ('1000', null,   'الأصول',                                 'Assets',                                  'ASSET',     'DEBIT',  false, 'NONE',              'ASSETS'),
  ('1100', '1000', 'الخزائن',                                'Cash boxes',                              'ASSET',     'DEBIT',  false, 'NONE',              'CASH_BOXES'),
  ('1200', '1000', 'الحسابات البنكية',                       'Bank accounts',                           'ASSET',     'DEBIT',  false, 'NONE',              'BANK_ACCOUNTS'),
  ('1300', '1000', 'مخزون السيارات',                         'Vehicle inventory',                       'ASSET',     'DEBIT',  true,  'VEHICLE',           'VEHICLE_INVENTORY'),
  ('1400', '1000', 'أقساط مستحقة على العملاء',               'Installment receivables',                 'ASSET',     'DEBIT',  true,  'CUSTOMER',          'INSTALLMENT_RECEIVABLE'),
  ('1410', '1000', 'مدينون آخرون',                           'Other receivables',                       'ASSET',     'DEBIT',  true,  'CUSTOMER',          'OTHER_RECEIVABLE'),
  ('1420', '1000', 'مستحقات لدى المعارض الأخرى',             'Receivable from external showrooms',      'ASSET',     'DEBIT',  true,  'EXTERNAL_SHOWROOM', 'EXTERNAL_SHOWROOM_RECEIVABLE'),
  ('1430', '1000', 'مصاريف مستردة من أصحاب سيارات الأمانة', 'Recoverable expenses from consignors',    'ASSET',     'DEBIT',  true,  'CONSIGNOR',         'CONSIGNOR_RECOVERABLE'),
  ('1500', '1000', 'سلف الشركاء',                            'Loans/advances to partners',              'ASSET',     'DEBIT',  true,  'PARTNER',           'PARTNER_LOANS_RECEIVABLE'),
  ('2000', null,   'الالتزامات',                             'Liabilities',                             'LIABILITY', 'CREDIT', false, 'NONE',              'LIABILITIES'),
  ('2100', '2000', 'مستحقات للبائعين',                       'Payable to sellers',                      'LIABILITY', 'CREDIT', true,  'CUSTOMER',          'SELLER_PAYABLE'),
  ('2200', '2000', 'مستحقات لأصحاب سيارات الأمانة',          'Payable to consignors',                   'LIABILITY', 'CREDIT', true,  'CONSIGNOR',         'CONSIGNOR_PAYABLE'),
  ('2300', '2000', 'عرابين العملاء',                         'Customer deposits',                       'LIABILITY', 'CREDIT', true,  'CUSTOMER',          'CUSTOMER_DEPOSITS'),
  ('2310', '2000', 'أرصدة دائنة للعملاء / مبالغ مستحقة الرد', 'Customer credits / refunds owed',        'LIABILITY', 'CREDIT', true,  'CUSTOMER',          'CUSTOMER_CREDITS'),
  ('2400', '2000', 'إيرادات تقسيط مؤجلة',                    'Deferred installment income',             'LIABILITY', 'CREDIT', true,  'CUSTOMER',          'DEFERRED_INSTALLMENT_INCOME'),
  ('2500', '2000', 'ضرائب مستحقة',                           'Taxes payable',                           'LIABILITY', 'CREDIT', true,  'NONE',              'TAXES_PAYABLE'),
  ('2600', '2000', 'قروض من الشركاء',                        'Loans from partners',                     'LIABILITY', 'CREDIT', true,  'PARTNER',           'PARTNER_LOANS_PAYABLE'),
  ('2700', '2000', 'مستحقات للموردين',                       'Payable to suppliers',                    'LIABILITY', 'CREDIT', true,  'SUPPLIER',          'SUPPLIER_PAYABLE'),
  ('3000', null,   'حقوق الملكية',                           'Equity',                                  'EQUITY',    'CREDIT', false, 'NONE',              'EQUITY'),
  ('3100', '3000', 'رأس مال الشركاء',                        'Partner capital',                         'EQUITY',    'CREDIT', true,  'PARTNER',           'PARTNER_CAPITAL'),
  ('3200', '3000', 'جاري الشركاء',                           'Partner current accounts',                'EQUITY',    'CREDIT', true,  'PARTNER',           'PARTNER_CURRENT'),
  ('3300', '3000', 'أرباح غير موزعة',                        'Retained earnings / undistributed profit','EQUITY',    'CREDIT', true,  'NONE',              'RETAINED_EARNINGS'),
  ('3310', '3000', 'أرباح موزعة مقدماً',                     'Profit allocated in advance',             'EQUITY',    'DEBIT',  true,  'NONE',              'PROFIT_ALLOCATED_IN_ADVANCE'),
  ('3900', '3000', 'أرصدة افتتاحية',                         'Opening balance equity',                  'EQUITY',    'CREDIT', true,  'NONE',              'OPENING_BALANCE_EQUITY'),
  ('4000', null,   'الإيرادات',                              'Income',                                  'INCOME',    'CREDIT', false, 'NONE',              'INCOME'),
  ('4100', '4000', 'مبيعات السيارات',                        'Vehicle sales',                           'INCOME',    'CREDIT', true,  'VEHICLE',           'VEHICLE_SALES'),
  ('4200', '4000', 'عمولات بيع سيارات الأمانة',              'Consignment commission income',           'INCOME',    'CREDIT', true,  'VEHICLE',           'CONSIGNMENT_COMMISSION'),
  ('4300', '4000', 'إيرادات التقسيط',                        'Installment financing income',            'INCOME',    'CREDIT', true,  'CUSTOMER',          'INSTALLMENT_FINANCING_INCOME'),
  ('4900', '4000', 'إيرادات أخرى',                           'Other income',                            'INCOME',    'CREDIT', true,  'NONE',              'OTHER_INCOME'),
  ('5000', null,   'تكلفة السيارات المباعة',                 'Cost of vehicles sold',                   'EXPENSE',   'DEBIT',  true,  'VEHICLE',           'COST_OF_VEHICLES_SOLD'),
  ('6000', null,   'المصروفات',                              'Expenses',                                'EXPENSE',   'DEBIT',  false, 'NONE',              'EXPENSES'),
  ('6100', '6000', 'عمولات المعارض الأخرى',                  'Commission paid to external showrooms',   'EXPENSE',   'DEBIT',  true,  'EXTERNAL_SHOWROOM', 'EXTERNAL_COMMISSION_EXPENSE'),
  ('6200', '6000', 'مصروفات عامة',                           'General expenses',                        'EXPENSE',   'DEBIT',  false, 'NONE',              'GENERAL_EXPENSES'),
  ('6210', '6200', 'إيجار',                                  'Rent',                                    'EXPENSE',   'DEBIT',  true,  'NONE',              'EXP_RENT'),
  ('6220', '6200', 'مرتبات',                                 'Salaries',                                'EXPENSE',   'DEBIT',  true,  'NONE',              'EXP_SALARIES'),
  ('6230', '6200', 'مرافق (كهرباء، مياه، إنترنت)',           'Utilities',                               'EXPENSE',   'DEBIT',  true,  'NONE',              'EXP_UTILITIES'),
  ('6240', '6200', 'دعاية وإعلان',                           'Advertising agency',                      'EXPENSE',   'DEBIT',  true,  'NONE',              'EXP_ADVERTISING'),
  ('6250', '6200', 'رسوم حكومية',                            'Government fees',                         'EXPENSE',   'DEBIT',  true,  'NONE',              'EXP_GOVERNMENT_FEES'),
  ('6260', '6200', 'إكراميات',                               'Tips',                                    'EXPENSE',   'DEBIT',  true,  'NONE',              'EXP_TIPS'),
  ('6290', '6200', 'مصروفات عامة أخرى',                      'Other general expenses',                  'EXPENSE',   'DEBIT',  true,  'NONE',              'EXP_OTHER');

-- -----------------------------------------------------------------------------
-- Tenant chart of accounts.
-- -----------------------------------------------------------------------------
create table public.ledger_accounts (
  id          uuid primary key default gen_random_uuid(),
  tenant_id   uuid not null references public.tenants (id),
  code        text not null check (code ~ '^[0-9]{4,6}$'),
  parent_id   uuid,
  name_ar     text not null,
  name_en     text not null,
  type        text not null check (type in ('ASSET', 'LIABILITY', 'EQUITY', 'INCOME', 'EXPENSE')),
  normal_side text not null check (normal_side in ('DEBIT', 'CREDIT')),
  is_postable boolean not null,
  is_system   boolean not null default false,
  subledger   text not null default 'NONE'
              check (subledger in ('NONE', 'PARTNER', 'CUSTOMER', 'VEHICLE', 'CONSIGNOR',
                                   'EXTERNAL_SHOWROOM', 'SUPPLIER', 'CASH_ACCOUNT')),
  system_key  text,
  archived_at timestamptz,
  created_at  timestamptz not null default now(),
  created_by  uuid,
  updated_at  timestamptz not null default now(),
  updated_by  uuid,
  unique (tenant_id, id),
  unique (tenant_id, code),
  foreign key (tenant_id, parent_id) references public.ledger_accounts (tenant_id, id)
);

create unique index ledger_accounts_system_key_idx on public.ledger_accounts (tenant_id, system_key)
  where system_key is not null;

-- Account identity is fixed once used: only names, archive state and the
-- postable flag of non-system accounts may change.
create or replace function private.protect_ledger_account()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  if new.tenant_id <> old.tenant_id or new.code <> old.code or new.type <> old.type
     or new.normal_side <> old.normal_side or new.subledger <> old.subledger
     or new.system_key is distinct from old.system_key
     or (old.parent_id is not null and new.parent_id is distinct from old.parent_id)
     or (old.is_system and new.is_postable <> old.is_postable) then
    raise exception 'ledger account identity cannot change' using errcode = 'SR003';
  end if;
  return new;
end;
$$;

create trigger ledger_accounts_protect
  before update on public.ledger_accounts
  for each row execute function private.protect_ledger_account();

-- -----------------------------------------------------------------------------
-- Cash boxes and bank accounts (SPEC §4.1, §4.10). Each owns one postable
-- sub-account under 1100 or 1200; balances are derived from journal lines.
-- -----------------------------------------------------------------------------
create table public.cash_accounts (
  id                uuid primary key default gen_random_uuid(),
  tenant_id         uuid not null references public.tenants (id),
  kind              text not null check (kind in ('CASH_BOX', 'BANK')),
  name_ar           text not null check (length(btrim(name_ar)) > 0),
  name_en           text,
  branch_id         uuid,
  ledger_account_id uuid not null,
  bank_name         text,
  account_number    text,
  iban              text,
  is_default        boolean not null default false,
  archived_at       timestamptz,
  created_at        timestamptz not null default now(),
  created_by        uuid,
  updated_at        timestamptz not null default now(),
  updated_by        uuid,
  unique (tenant_id, id),
  unique (tenant_id, ledger_account_id),
  foreign key (tenant_id, ledger_account_id) references public.ledger_accounts (tenant_id, id),
  foreign key (tenant_id, branch_id) references public.branches (tenant_id, id)
);

create unique index cash_accounts_one_default_idx on public.cash_accounts (tenant_id)
  where is_default and archived_at is null;

-- -----------------------------------------------------------------------------
-- Expense categories (SPEC §4.1). GENERAL categories post to their own 62xx
-- account; VEHICLE categories are labels (owned-car costs capitalise to 1300).
-- -----------------------------------------------------------------------------
create table public.expense_categories (
  id                uuid primary key default gen_random_uuid(),
  tenant_id         uuid not null references public.tenants (id),
  kind              text not null check (kind in ('VEHICLE', 'GENERAL')),
  code              text not null check (code ~ '^[a-z_]+$'),
  name_ar           text not null,
  name_en           text not null,
  ledger_account_id uuid,
  is_seeded         boolean not null default false,
  sort_order        smallint not null default 100,
  archived_at       timestamptz,
  created_at        timestamptz not null default now(),
  created_by        uuid,
  updated_at        timestamptz not null default now(),
  updated_by        uuid,
  unique (tenant_id, id),
  unique (tenant_id, kind, code),
  foreign key (tenant_id, ledger_account_id) references public.ledger_accounts (tenant_id, id),
  check ((kind = 'GENERAL') = (ledger_account_id is not null))
);

-- -----------------------------------------------------------------------------
-- Payment methods (SPEC §4.10): configurable labels, each with a default
-- cash/bank account to suggest.
-- -----------------------------------------------------------------------------
create table public.payment_methods (
  id                      uuid primary key default gen_random_uuid(),
  tenant_id               uuid not null references public.tenants (id),
  code                    text not null check (code ~ '^[a-z_]+$'),
  name_ar                 text not null,
  name_en                 text not null,
  default_cash_account_id uuid,
  sort_order              smallint not null default 100,
  archived_at             timestamptz,
  created_at              timestamptz not null default now(),
  created_by              uuid,
  updated_at              timestamptz not null default now(),
  updated_by              uuid,
  unique (tenant_id, id),
  unique (tenant_id, code),
  foreign key (tenant_id, default_cash_account_id) references public.cash_accounts (tenant_id, id)
);

-- -----------------------------------------------------------------------------
-- Per-tenant seed: chart of accounts, expense categories, payment methods.
-- Runs for every new tenant and once below for tenants created before Phase 2.
-- -----------------------------------------------------------------------------
create or replace function private.seed_tenant_accounting(p_tenant uuid)
returns void
language plpgsql
security definer
set search_path = ''
as $$
begin
  -- Accounts, parents before children (template codes sort parents first).
  insert into public.ledger_accounts
    (tenant_id, code, name_ar, name_en, type, normal_side, is_postable, is_system, subledger, system_key, parent_id)
  select p_tenant, t.code, t.name_ar, t.name_en, t.type, t.normal_side, t.is_postable, true, t.subledger, t.system_key, null
    from public.coa_template t
   order by t.code
  on conflict (tenant_id, code) do nothing;

  update public.ledger_accounts a
     set parent_id = p.id
    from public.coa_template t
    join public.ledger_accounts p on p.tenant_id = p_tenant and p.code = t.parent_code
   where a.tenant_id = p_tenant and a.code = t.code and a.parent_id is null and t.parent_code is not null;

  insert into public.expense_categories (tenant_id, kind, code, name_ar, name_en, ledger_account_id, is_seeded, sort_order)
  select p_tenant, 'GENERAL', c.code, c.name_ar, c.name_en, a.id, true, c.sort_order
    from (values
      ('rent',            'إيجار',          'Rent',             'EXP_RENT',            10),
      ('salaries',        'مرتبات',         'Salaries',         'EXP_SALARIES',        20),
      ('utilities',       'مرافق',          'Utilities',        'EXP_UTILITIES',       30),
      ('advertising',     'دعاية وإعلان',   'Advertising',      'EXP_ADVERTISING',     40),
      ('government_fees', 'رسوم حكومية',    'Government fees',  'EXP_GOVERNMENT_FEES', 50),
      ('tips',            'إكراميات',       'Tips',             'EXP_TIPS',            60),
      ('other',           'أخرى',           'Other',            'EXP_OTHER',           90)
    ) as c (code, name_ar, name_en, system_key, sort_order)
    join public.ledger_accounts a on a.tenant_id = p_tenant and a.system_key = c.system_key
  on conflict (tenant_id, kind, code) do nothing;

  insert into public.expense_categories (tenant_id, kind, code, name_ar, name_en, is_seeded, sort_order)
  select p_tenant, 'VEHICLE', c.code, c.name_ar, c.name_en, true, c.sort_order
    from (values
      ('maintenance',     'صيانة',          'Maintenance',      10),
      ('bodywork',        'سمكرة',          'Bodywork',         20),
      ('paint',           'دهان',           'Paint',            30),
      ('polishing',       'تلميع',          'Polishing',        40),
      ('cleaning',        'غسيل وتنظيف',    'Cleaning',         50),
      ('license_renewal', 'تجديد رخصة',     'License renewal',  60),
      ('transport',       'نقل',            'Transport',        70),
      ('inspection',      'فحص',            'Inspection',       80),
      ('tips',            'إكرامية',        'Tips',             85),
      ('other',           'أخرى',           'Other',            90)
    ) as c (code, name_ar, name_en, sort_order)
  on conflict (tenant_id, kind, code) do nothing;

  insert into public.payment_methods (tenant_id, code, name_ar, name_en, sort_order)
  values
    (p_tenant, 'cash',          'نقدي',          'Cash',          10),
    (p_tenant, 'bank_transfer', 'تحويل بنكي',    'Bank transfer', 20),
    (p_tenant, 'card',          'بطاقة',         'Card',          30),
    (p_tenant, 'cheque',        'شيك',           'Cheque',        40),
    (p_tenant, 'other',         'أخرى',          'Other',         90)
  on conflict (tenant_id, code) do nothing;
end;
$$;

create or replace function private.seed_tenant_accounting_trigger()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
  perform private.seed_tenant_accounting(new.id);
  return null;
end;
$$;

create trigger tenants_seed_accounting
  after insert on public.tenants
  for each row execute function private.seed_tenant_accounting_trigger();

select private.seed_tenant_accounting(id) from public.tenants;

-- -----------------------------------------------------------------------------
-- Security.
-- -----------------------------------------------------------------------------
call private.secure_table('public.coa_template', p_touch => false, p_audit => false);
call private.secure_table('public.ledger_accounts');
call private.secure_table('public.cash_accounts');
call private.secure_table('public.expense_categories');
call private.secure_table('public.payment_methods');
revoke insert, update on table public.coa_template from app_api;

create policy coa_template_read on public.coa_template
  for select to authenticated, app_api using (true);

-- Accounts, cash accounts, categories and methods are visible to members who
-- work with money; names are not sensitive, balances are computed elsewhere.
create policy ledger_accounts_read on public.ledger_accounts
  for select to authenticated
  using (tenant_id = any ((select private.tenants_with_permission('cash.view'))::uuid[])
      or tenant_id = any ((select private.tenants_with_permission('journal.view'))::uuid[]));

create policy cash_accounts_read on public.cash_accounts
  for select to authenticated
  using (tenant_id = any ((select private.tenants_with_permission('cash.view'))::uuid[]));

create policy expense_categories_read on public.expense_categories
  for select to authenticated
  using (tenant_id = any ((select private.my_tenant_ids())::uuid[]));

create policy payment_methods_read on public.payment_methods
  for select to authenticated
  using (tenant_id = any ((select private.my_tenant_ids())::uuid[]));

create policy ledger_accounts_api on public.ledger_accounts
  for all to app_api
  using (tenant_id = (select private.current_tenant_id()))
  with check (tenant_id = (select private.current_tenant_id()));

create policy cash_accounts_api on public.cash_accounts
  for all to app_api
  using (tenant_id = (select private.current_tenant_id()))
  with check (tenant_id = (select private.current_tenant_id()));

create policy expense_categories_api on public.expense_categories
  for all to app_api
  using (tenant_id = (select private.current_tenant_id()))
  with check (tenant_id = (select private.current_tenant_id()));

create policy payment_methods_api on public.payment_methods
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
