-- =============================================================================
-- LOCAL DEVELOPMENT SEED ONLY. Never run against a shared or production
-- database: it sets a known password on app_api and creates demo users.
--
-- Demo users (password for all: Demo-Pass-2026):
--   owner@nour.example        OWNER of معرض النور للسيارات (EG)
--   accountant@nour.example   ACCOUNTANT of معرض النور
--   sales@nour.example        SALES of معرض النور
--   partner@nour.example      PARTNER of معرض النور and PARTNER of Doha Motors (multi-tenant)
--   owner@doha.example        OWNER of Doha Motors (QA) — the "other tenant" for isolation tests
-- =============================================================================

alter role app_api with login password 'app_api_local_dev';

-- Fixed ids keep tests and E2E scripts readable.
-- Tenants
--   11111111-...  معرض النور للسيارات (EG)
--   22222222-...  Doha Motors (QA)
-- Users
--   a0000000-...-0001 owner@nour.example
--   a0000000-...-0002 accountant@nour.example
--   a0000000-...-0003 sales@nour.example
--   a0000000-...-0004 partner@nour.example
--   b0000000-...-0001 owner@doha.example

do $$
declare
  v_users constant jsonb := '[
    {"id": "a0000000-0000-0000-0000-000000000001", "email": "owner@nour.example",      "name": "أحمد المالك"},
    {"id": "a0000000-0000-0000-0000-000000000002", "email": "accountant@nour.example", "name": "منى المحاسبة"},
    {"id": "a0000000-0000-0000-0000-000000000003", "email": "sales@nour.example",      "name": "كريم المبيعات"},
    {"id": "a0000000-0000-0000-0000-000000000004", "email": "partner@nour.example",    "name": "يوسف الشريك"},
    {"id": "b0000000-0000-0000-0000-000000000001", "email": "owner@doha.example",      "name": "Khalid Owner"}
  ]';
  v_user jsonb;
begin
  for v_user in select * from jsonb_array_elements(v_users) loop
    insert into auth.users (
      instance_id, id, aud, role, email, encrypted_password, email_confirmed_at,
      raw_app_meta_data, raw_user_meta_data, created_at, updated_at,
      confirmation_token, recovery_token, email_change, email_change_token_new
    ) values (
      '00000000-0000-0000-0000-000000000000',
      (v_user ->> 'id')::uuid,
      'authenticated', 'authenticated',
      v_user ->> 'email',
      extensions.crypt('Demo-Pass-2026', extensions.gen_salt('bf')),
      now(),
      '{"provider": "email", "providers": ["email"]}',
      jsonb_build_object('full_name', v_user ->> 'name'),
      now(), now(), '', '', '', ''
    );

    insert into auth.identities (
      id, user_id, provider_id, provider, identity_data, last_sign_in_at, created_at, updated_at
    ) values (
      gen_random_uuid(),
      (v_user ->> 'id')::uuid,
      v_user ->> 'id',
      'email',
      jsonb_build_object('sub', v_user ->> 'id', 'email', v_user ->> 'email', 'email_verified', true),
      now(), now(), now()
    );
  end loop;
end
$$;

insert into public.tenants (id, name_ar, name_en, country_code, currency_code, timezone, commercial_reg_no, address, phones)
values
  ('11111111-1111-1111-1111-111111111111', 'معرض النور للسيارات', 'Al Nour Motors', 'EG', 'EGP', 'Africa/Cairo',
   '123456', 'شارع التسعين، القاهرة الجديدة', '{"+201000000001"}'),
  ('22222222-2222-2222-2222-222222222222', 'معرض الدوحة للسيارات', 'Doha Motors', 'QA', 'QAR', 'Asia/Qatar',
   'QA-98765', 'Salwa Road, Doha', '{"+97440000001"}');

insert into public.branches (tenant_id, name_ar, name_en, is_default) values
  ('11111111-1111-1111-1111-111111111111', 'المعرض الرئيسي', 'Main yard', true),
  ('22222222-2222-2222-2222-222222222222', 'الفرع الرئيسي', 'Main branch', true);

insert into public.subscriptions (tenant_id, plan_id, status, trial_ends_at)
select t.id, p.id, 'TRIAL', now() + interval '30 days'
from public.tenants t
cross join public.plans p
where p.code = 'TRIAL';

insert into public.memberships (tenant_id, user_id, role_id)
select m.tenant_id::uuid, m.user_id::uuid, r.id
from (values
  ('11111111-1111-1111-1111-111111111111', 'a0000000-0000-0000-0000-000000000001', 'OWNER'),
  ('11111111-1111-1111-1111-111111111111', 'a0000000-0000-0000-0000-000000000002', 'ACCOUNTANT'),
  ('11111111-1111-1111-1111-111111111111', 'a0000000-0000-0000-0000-000000000003', 'SALES'),
  ('11111111-1111-1111-1111-111111111111', 'a0000000-0000-0000-0000-000000000004', 'PARTNER'),
  ('22222222-2222-2222-2222-222222222222', 'a0000000-0000-0000-0000-000000000004', 'PARTNER'),
  ('22222222-2222-2222-2222-222222222222', 'b0000000-0000-0000-0000-000000000001', 'OWNER')
) as m (tenant_id, user_id, role_code)
join public.roles r on r.code = m.role_code and r.tenant_id is null;

-- =============================================================================
-- Phase 2: cash and bank accounts and a few postings, made through the same
-- database function the API uses (post_journal_entry), so the seed obeys
-- every ledger rule.
--   معرض النور: الخزنة الرئيسية (1101), بنك CIB (1201)
--     2026-09-01 opening balances (rule 25): cash 200,000 + bank 800,000 / opening equity 1,000,000
--     2026-09-05 rent 25,000 paid by bank (rule 20)
--     2026-09-10 bank -> cash transfer 50,000 (rule 21)
--   Doha Motors: main cash box (1101), opening 50,000 QAR
-- =============================================================================
do $$
declare
  v_nour  constant uuid := '11111111-1111-1111-1111-111111111111';
  v_doha  constant uuid := '22222222-2222-2222-2222-222222222222';
  v_cash  constant uuid := 'c0000000-0000-0000-0000-000000000001';
  v_bank  constant uuid := 'c0000000-0000-0000-0000-000000000002';
  v_dcash constant uuid := 'c0000000-0000-0000-0000-000000000003';
  v_cash_la uuid;
  v_bank_la uuid;
  v_dcash_la uuid;
  v_entry record;
  v_doc uuid;
begin
  insert into public.ledger_accounts (tenant_id, code, parent_id, name_ar, name_en, type, normal_side, is_postable, subledger)
  values (v_nour, '1101', (select id from public.ledger_accounts where tenant_id = v_nour and code = '1100'),
          'الخزنة الرئيسية', 'Main cash box', 'ASSET', 'DEBIT', true, 'CASH_ACCOUNT')
  returning id into v_cash_la;
  insert into public.ledger_accounts (tenant_id, code, parent_id, name_ar, name_en, type, normal_side, is_postable, subledger)
  values (v_nour, '1201', (select id from public.ledger_accounts where tenant_id = v_nour and code = '1200'),
          'بنك CIB', 'CIB bank', 'ASSET', 'DEBIT', true, 'CASH_ACCOUNT')
  returning id into v_bank_la;
  insert into public.ledger_accounts (tenant_id, code, parent_id, name_ar, name_en, type, normal_side, is_postable, subledger)
  values (v_doha, '1101', (select id from public.ledger_accounts where tenant_id = v_doha and code = '1100'),
          'الخزنة الرئيسية', 'Main cash box', 'ASSET', 'DEBIT', true, 'CASH_ACCOUNT')
  returning id into v_dcash_la;

  insert into public.cash_accounts (id, tenant_id, kind, name_ar, name_en, ledger_account_id, is_default) values
    (v_cash, v_nour, 'CASH_BOX', 'الخزنة الرئيسية', 'Main cash box', v_cash_la, true),
    (v_dcash, v_doha, 'CASH_BOX', 'الخزنة الرئيسية', 'Main cash box', v_dcash_la, true);
  insert into public.cash_accounts (id, tenant_id, kind, name_ar, name_en, ledger_account_id, bank_name, account_number)
  values (v_bank, v_nour, 'BANK', 'بنك CIB', 'CIB bank', v_bank_la, 'Commercial International Bank', '100012345678');

  -- معرض النور
  perform set_config('app.tenant_id', v_nour::text, true);

  perform private.post_journal_entry(jsonb_build_object(
    'entry_date', '2026-09-01', 'description', 'أرصدة افتتاحية', 'source_type', 'OPENING_BALANCE', 'is_opening', true,
    'lines', jsonb_build_array(
      jsonb_build_object('ledger_account_id', v_cash_la, 'debit', '200000.00', 'cash_account_id', v_cash),
      jsonb_build_object('ledger_account_id', v_bank_la, 'debit', '800000.00', 'cash_account_id', v_bank),
      jsonb_build_object('ledger_account_id',
        (select id from public.ledger_accounts where tenant_id = v_nour and system_key = 'OPENING_BALANCE_EQUITY'),
        'credit', '1000000.00'))));

  v_doc := gen_random_uuid();
  select * into v_entry from private.post_journal_entry(jsonb_build_object(
    'entry_date', '2026-09-05', 'description', 'إيجار شهر سبتمبر', 'source_type', 'GENERAL_EXPENSE', 'source_id', v_doc,
    'lines', jsonb_build_array(
      jsonb_build_object('ledger_account_id',
        (select id from public.ledger_accounts where tenant_id = v_nour and system_key = 'EXP_RENT'), 'debit', '25000.00'),
      jsonb_build_object('ledger_account_id', v_bank_la, 'credit', '25000.00', 'cash_account_id', v_bank))));
  insert into public.general_expenses
    (id, tenant_id, expense_date, category_id, amount, description, cash_account_id, journal_entry_id)
  values (v_doc, v_nour, '2026-09-05',
          (select id from public.expense_categories where tenant_id = v_nour and kind = 'GENERAL' and code = 'rent'),
          25000.00, 'إيجار شهر سبتمبر', v_bank, v_entry.journal_entry_id);

  v_doc := gen_random_uuid();
  select * into v_entry from private.post_journal_entry(jsonb_build_object(
    'entry_date', '2026-09-10', 'description', 'سحب نقدية من البنك للخزنة', 'source_type', 'TRANSFER', 'source_id', v_doc,
    'lines', jsonb_build_array(
      jsonb_build_object('ledger_account_id', v_cash_la, 'debit', '50000.00', 'cash_account_id', v_cash),
      jsonb_build_object('ledger_account_id', v_bank_la, 'credit', '50000.00', 'cash_account_id', v_bank))));
  insert into public.transfers
    (id, tenant_id, transfer_date, from_cash_account_id, to_cash_account_id, amount, notes, journal_entry_id)
  values (v_doc, v_nour, '2026-09-10', v_bank, v_cash, 50000.00, 'سحب نقدية من البنك للخزنة', v_entry.journal_entry_id);

  -- Doha Motors
  perform set_config('app.tenant_id', v_doha::text, true);
  perform private.post_journal_entry(jsonb_build_object(
    'entry_date', '2026-09-01', 'description', 'Opening balances', 'source_type', 'OPENING_BALANCE', 'is_opening', true,
    'lines', jsonb_build_array(
      jsonb_build_object('ledger_account_id', v_dcash_la, 'debit', '50000.00', 'cash_account_id', v_dcash),
      jsonb_build_object('ledger_account_id',
        (select id from public.ledger_accounts where tenant_id = v_doha and system_key = 'OPENING_BALANCE_EQUITY'),
        'credit', '50000.00'))));

  perform set_config('app.tenant_id', '', true);
end
$$;

-- =============================================================================
-- Phase 3: partners, ownership and capital, posted through post_journal_entry.
--   معرض النور: أحمد 50% (owner@), منى 30%, يوسف 20% (partner@) from 2026-01-01;
--     capital contributions into بنك CIB on 2026-09-02 (rule 1): 500,000 / 300,000 / 200,000
--   Doha Motors: Khalid 70% (owner@doha), Youssef 30% (partner@ — the same person, a second showroom)
-- =============================================================================
do $$
declare
  v_nour   constant uuid := '11111111-1111-1111-1111-111111111111';
  v_doha   constant uuid := '22222222-2222-2222-2222-222222222222';
  v_bank   constant uuid := 'c0000000-0000-0000-0000-000000000002';
  v_ahmed  constant uuid := 'f0000000-0000-0000-0000-000000000001';
  v_mona   constant uuid := 'f0000000-0000-0000-0000-000000000002';
  v_yousef constant uuid := 'f0000000-0000-0000-0000-000000000003';
  v_khalid constant uuid := 'f0000000-0000-0000-0000-000000000011';
  v_yousef_doha constant uuid := 'f0000000-0000-0000-0000-000000000013';
  v_bank_la uuid;
  v_capital uuid;
  v_entry record;
  v_doc uuid;
  v_partner record;
begin
  insert into public.partners (id, tenant_id, name_ar, name_en, phone) values
    (v_ahmed,  v_nour, 'أحمد السيد',  'Ahmed El-Sayed', '+201000000011'),
    (v_mona,   v_nour, 'منى عبد الله', 'Mona Abdallah',  '+201000000012'),
    (v_yousef, v_nour, 'يوسف حسن',    'Youssef Hassan', '+201000000013'),
    (v_khalid, v_doha, 'خالد المري',   'Khalid Al-Marri', '+97440000011'),
    (v_yousef_doha, v_doha, 'يوسف حسن', 'Youssef Hassan', '+201000000013');

  insert into public.partner_share_history (tenant_id, partner_id, percentage, effective_from, change_batch_id) values
    (v_nour, v_ahmed,  50, '2026-01-01', 'a1000000-0000-0000-0000-000000000001'),
    (v_nour, v_mona,   30, '2026-01-01', 'a1000000-0000-0000-0000-000000000001'),
    (v_nour, v_yousef, 20, '2026-01-01', 'a1000000-0000-0000-0000-000000000001'),
    (v_doha, v_khalid, 70, '2026-01-01', 'a1000000-0000-0000-0000-000000000002'),
    (v_doha, v_yousef_doha, 30, '2026-01-01', 'a1000000-0000-0000-0000-000000000002');

  update public.memberships set partner_id = v_ahmed
   where tenant_id = v_nour and user_id = 'a0000000-0000-0000-0000-000000000001';
  update public.memberships set partner_id = v_yousef
   where tenant_id = v_nour and user_id = 'a0000000-0000-0000-0000-000000000004';
  update public.memberships set partner_id = v_khalid
   where tenant_id = v_doha and user_id = 'b0000000-0000-0000-0000-000000000001';
  update public.memberships set partner_id = v_yousef_doha
   where tenant_id = v_doha and user_id = 'a0000000-0000-0000-0000-000000000004';

  -- Capital contributions (rule 1): Dr bank / Cr partner capital
  perform set_config('app.tenant_id', v_nour::text, true);
  select ledger_account_id into v_bank_la from public.cash_accounts where id = v_bank;
  select id into v_capital from public.ledger_accounts where tenant_id = v_nour and system_key = 'PARTNER_CAPITAL';

  for v_partner in
    select * from (values (v_ahmed, 500000.00, 'أحمد السيد'), (v_mona, 300000.00, 'منى عبد الله'),
                          (v_yousef, 200000.00, 'يوسف حسن')) as p (id, amount, name)
  loop
    v_doc := gen_random_uuid();
    select * into v_entry from private.post_journal_entry(jsonb_build_object(
      'entry_date', '2026-09-02', 'description', 'مساهمة في رأس المال — ' || v_partner.name,
      'source_type', 'PARTNER_CONTRIBUTION', 'source_id', v_doc,
      'lines', jsonb_build_array(
        jsonb_build_object('ledger_account_id', v_bank_la, 'debit', v_partner.amount::text, 'cash_account_id', v_bank),
        jsonb_build_object('ledger_account_id', v_capital, 'credit', v_partner.amount::text,
                           'partner_id', v_partner.id))));
    insert into public.partner_transactions
      (id, tenant_id, partner_id, type, txn_date, amount, cash_account_id, journal_entry_id)
    values (v_doc, v_nour, v_partner.id, 'CONTRIBUTION', '2026-09-02', v_partner.amount, v_bank, v_entry.journal_entry_id);
  end loop;

  perform set_config('app.tenant_id', '', true);
end
$$;
