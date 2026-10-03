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

-- =============================================================================
-- Phase 4: customers, a workshop, five cars and their money (معرض النور).
--   Elantra 2019   bought 09-03 for 400,000 (bank), paint 15,000 (cash)        AVAILABLE
--   Corolla 2020   bought 09-04 for 520,000: 400,000 bank + 120,000 owed Karim  AVAILABLE
--   Sportage 2021  bought 09-08 for 650,000 (bank); Sara's deposit 20,000 cash  RESERVED
--   Sunny 2018     bought 09-05 for 220,000 (cash), maintenance 8,000 on credit
--                  from ورشة الأمل; sold 09-25 to Hassan for 260,000 cash        SOLD (profit 32,000)
--   Optra 2016     bought 09-28 for 150,000 (bank)                             IN_PREPARATION
--   Cash 250,000 -220,000 -15,000 +260,000 +20,000 = 295,000
--   Bank 1,725,000 -400,000 -400,000 -650,000 -150,000 = 125,000
-- =============================================================================
do $$
declare
  v_nour    constant uuid := '11111111-1111-1111-1111-111111111111';
  v_cash    constant uuid := 'c0000000-0000-0000-0000-000000000001';
  v_bank    constant uuid := 'c0000000-0000-0000-0000-000000000002';
  v_owner   constant uuid := 'a0000000-0000-0000-0000-000000000001';
  v_karim   constant uuid := 'd0000000-0000-0000-0000-000000000001';
  v_hassan  constant uuid := 'd0000000-0000-0000-0000-000000000002';
  v_sara    constant uuid := 'd0000000-0000-0000-0000-000000000003';
  v_garage  constant uuid := 'd1000000-0000-0000-0000-000000000001';
  v_elantra constant uuid := 'e1000000-0000-0000-0000-000000000001';
  v_corolla constant uuid := 'e1000000-0000-0000-0000-000000000002';
  v_sport   constant uuid := 'e1000000-0000-0000-0000-000000000003';
  v_sunny   constant uuid := 'e1000000-0000-0000-0000-000000000004';
  v_optra   constant uuid := 'e1000000-0000-0000-0000-000000000005';
  v_sale    constant uuid := 'd2000000-0000-0000-0000-000000000001';
  v_inv     uuid;
  v_payable uuid;
  v_supp    uuid;
  v_dep     uuid;
  v_sales   uuid;
  v_cogs    uuid;
  p         record;
  v_entry   record;
  v_cost    record;
  v_doc     uuid;
begin
  perform set_config('app.tenant_id', v_nour::text, true);
  select id into v_inv from public.ledger_accounts where tenant_id = v_nour and system_key = 'VEHICLE_INVENTORY';
  select id into v_payable from public.ledger_accounts where tenant_id = v_nour and system_key = 'SELLER_PAYABLE';
  select id into v_supp from public.ledger_accounts where tenant_id = v_nour and system_key = 'SUPPLIER_PAYABLE';
  select id into v_dep from public.ledger_accounts where tenant_id = v_nour and system_key = 'CUSTOMER_DEPOSITS';
  select id into v_sales from public.ledger_accounts where tenant_id = v_nour and system_key = 'VEHICLE_SALES';
  select id into v_cogs from public.ledger_accounts where tenant_id = v_nour and system_key = 'COST_OF_VEHICLES_SOLD';

  insert into public.customers (id, tenant_id, name, phone_primary, is_seller, is_buyer) values
    (v_karim,  v_nour, 'كريم محمود',    '+201001112233', true,  false),
    (v_hassan, v_nour, 'حسن علي',       '+201002223344', false, true),
    (v_sara,   v_nour, 'سارة إبراهيم',  '+201003334455', false, false);
  insert into public.suppliers (id, tenant_id, name, kind, phone)
  values (v_garage, v_nour, 'ورشة الأمل', 'WORKSHOP', '+201004445566');

  insert into public.vehicles (id, tenant_id, make, model, year, color_ext, transmission, fuel, mileage_km, vin,
                               plate_no, asking_price, min_price, current_location_id)
  select v.id, v_nour, v.make, v.model, v.year, v.color, 'AUTOMATIC', 'PETROL', v.km, v.vin, v.plate, v.asking, v.min_price,
         (select id from public.locations where tenant_id = v_nour and is_default)
    from (values
      (v_elantra, 'Hyundai',   'Elantra',  2019, 'أبيض',  62000, 'KMHD841CBKU123456', 'ط ص ع 1234', 480000.00, 460000.00),
      (v_corolla, 'Toyota',    'Corolla',  2020, 'فضي',   48000, 'JTDBR32E720045678', 'ن ب ل 5678', 590000.00, 570000.00),
      (v_sport,   'Kia',       'Sportage', 2021, 'أسود',  31000, 'KNAPM81AAM7012345', 'س ق ر 9012', 720000.00, 700000.00),
      (v_sunny,   'Nissan',    'Sunny',    2018, 'أحمر',  95000, '3N1CN7AP5JL801234', 'م ع ل 3456', 270000.00, 255000.00),
      (v_optra,   'Chevrolet', 'Optra',    2016, 'رمادي', 140000, 'KL1JF6969GK567890', 'ه د و 7890', 185000.00, 170000.00)
    ) as v (id, make, model, year, color, km, vin, plate, asking, min_price);

  -- Purchases (rules 6, 7)
  for p in
    select * from (values
      (v_elantra, '2026-09-03'::date, 400000.00, 400000.00, v_bank, 'هيونداي إلنترا 2019'),
      (v_corolla, '2026-09-04'::date, 520000.00, 400000.00, v_bank, 'تويوتا كورولا 2020'),
      (v_sunny,   '2026-09-05'::date, 220000.00, 220000.00, v_cash, 'نيسان صني 2018'),
      (v_sport,   '2026-09-08'::date, 650000.00, 650000.00, v_bank, 'كيا سبورتاج 2021'),
      (v_optra,   '2026-09-28'::date, 150000.00, 150000.00, v_bank, 'شيفروليه أوبترا 2016')
    ) as x (vehicle_id, d, price, paid, cash_id, label)
  loop
    v_doc := gen_random_uuid();
    select * into v_entry from private.post_journal_entry(jsonb_build_object(
      'entry_date', p.d, 'description', 'شراء ' || p.label || ' من كريم محمود',
      'source_type', 'VEHICLE_PURCHASE', 'source_id', v_doc,
      'lines', jsonb_build_array(
        jsonb_build_object('ledger_account_id', v_inv, 'debit', p.price::text, 'vehicle_id', p.vehicle_id),
        jsonb_build_object('ledger_account_id', (select ledger_account_id from public.cash_accounts where id = p.cash_id),
                           'credit', p.paid::text, 'cash_account_id', p.cash_id))
      || case when p.price > p.paid then jsonb_build_array(
        jsonb_build_object('ledger_account_id', v_payable, 'credit', (p.price - p.paid)::text,
                           'customer_id', v_karim, 'vehicle_id', p.vehicle_id))
         else '[]'::jsonb end));
    insert into public.vehicle_purchases
      (id, tenant_id, vehicle_id, seller_customer_id, purchase_date, price, deferred_amount, journal_entry_id)
    values (v_doc, v_nour, p.vehicle_id, v_karim, p.d, p.price, p.price - p.paid, v_entry.journal_entry_id);
    insert into public.purchase_payments (tenant_id, purchase_id, cash_account_id, amount)
    values (v_nour, v_doc, p.cash_id, p.paid);
    update public.vehicles set stock_date = p.d, status = 'IN_PREPARATION' where id = p.vehicle_id;
  end loop;

  -- Expenses: rule 9 (cash) and rule 31 (on credit from the workshop)
  v_doc := gen_random_uuid();
  select * into v_entry from private.post_journal_entry(jsonb_build_object(
    'entry_date', '2026-09-06', 'description', 'دهان — هيونداي إلنترا 2019', 'source_type', 'VEHICLE_EXPENSE',
    'source_id', v_doc,
    'lines', jsonb_build_array(
      jsonb_build_object('ledger_account_id', v_inv, 'debit', '15000.00', 'vehicle_id', v_elantra, 'memo', 'دهان'),
      jsonb_build_object('ledger_account_id', (select ledger_account_id from public.cash_accounts where id = v_cash),
                         'credit', '15000.00', 'cash_account_id', v_cash))));
  insert into public.vehicle_expenses
    (id, tenant_id, vehicle_id, category_id, expense_date, amount, funding, cash_account_id, journal_entry_id)
  values (v_doc, v_nour, v_elantra,
          (select id from public.expense_categories where tenant_id = v_nour and kind = 'VEHICLE' and code = 'paint'),
          '2026-09-06', 15000.00, 'CASH_ACCOUNT', v_cash, v_entry.journal_entry_id);

  v_doc := gen_random_uuid();
  select * into v_entry from private.post_journal_entry(jsonb_build_object(
    'entry_date', '2026-09-07', 'description', 'صيانة — نيسان صني 2018', 'source_type', 'VEHICLE_EXPENSE',
    'source_id', v_doc,
    'lines', jsonb_build_array(
      jsonb_build_object('ledger_account_id', v_inv, 'debit', '8000.00', 'vehicle_id', v_sunny, 'memo', 'صيانة'),
      jsonb_build_object('ledger_account_id', v_supp, 'credit', '8000.00', 'supplier_id', v_garage))));
  insert into public.vehicle_expenses
    (id, tenant_id, vehicle_id, category_id, expense_date, amount, funding, supplier_id, journal_entry_id)
  values (v_doc, v_nour, v_sunny,
          (select id from public.expense_categories where tenant_id = v_nour and kind = 'VEHICLE' and code = 'maintenance'),
          '2026-09-07', 8000.00, 'SUPPLIER_CREDIT', v_garage, v_entry.journal_entry_id);

  update public.vehicles set status = 'AVAILABLE' where id in (v_elantra, v_corolla, v_sport, v_sunny);

  -- Sara reserves the Sportage (rule 11)
  v_doc := gen_random_uuid();
  select * into v_entry from private.post_journal_entry(jsonb_build_object(
    'entry_date', '2026-09-28', 'description', 'عربون كيا سبورتاج 2021 من سارة إبراهيم', 'source_type', 'DEPOSIT',
    'source_id', v_doc,
    'lines', jsonb_build_array(
      jsonb_build_object('ledger_account_id', (select ledger_account_id from public.cash_accounts where id = v_cash),
                         'debit', '20000.00', 'cash_account_id', v_cash),
      jsonb_build_object('ledger_account_id', v_dep, 'credit', '20000.00', 'customer_id', v_sara, 'vehicle_id', v_sport))));
  insert into public.reservations
    (id, tenant_id, vehicle_id, customer_id, reservation_date, deposit_amount, cash_account_id, expires_on,
     journal_entry_id)
  values (v_doc, v_nour, v_sport, v_sara, '2026-09-28', 20000.00, v_cash, '2026-10-12', v_entry.journal_entry_id);
  update public.vehicles set status = 'RESERVED' where id = v_sport;

  -- Hassan buys the Sunny for 260,000 cash (rule 12 + cost recognition, D-28)
  insert into public.tenant_counters (tenant_id, counter_key, last_value) values
    (v_nour, 'sale-2026', 1), (v_nour, 'invoice-2026', 1);
  insert into public.sales (id, tenant_id, sale_no, vehicle_id, buyer_customer_id, sale_date, list_price, discount,
                            sale_price, created_by)
  values (v_sale, v_nour, 'S-2026-0001', v_sunny, v_hassan, '2026-09-25', 270000.00, 10000.00, 260000.00, v_owner);
  insert into public.sale_payments (tenant_id, sale_id, cash_account_id, amount)
  values (v_nour, v_sale, v_cash, 260000.00);
  select * into v_entry from private.post_journal_entry(jsonb_build_object(
    'entry_date', '2026-09-25', 'description', 'بيع نيسان صني 2018 إلى حسن علي — S-2026-0001', 'source_type', 'SALE',
    'source_id', v_sale,
    'lines', jsonb_build_array(
      jsonb_build_object('ledger_account_id', (select ledger_account_id from public.cash_accounts where id = v_cash),
                         'debit', '260000.00', 'cash_account_id', v_cash),
      jsonb_build_object('ledger_account_id', v_sales, 'credit', '260000.00', 'vehicle_id', v_sunny))));
  select * into v_cost from private.post_journal_entry(jsonb_build_object(
    'entry_date', '2026-09-25', 'description', 'تكلفة نيسان صني 2018 — S-2026-0001', 'source_type', 'SALE_COST',
    'source_id', v_sale,
    'lines', jsonb_build_array(
      jsonb_build_object('ledger_account_id', v_cogs, 'debit', '228000.00', 'vehicle_id', v_sunny),
      jsonb_build_object('ledger_account_id', v_inv, 'credit', '228000.00', 'vehicle_id', v_sunny))));
  update public.sales
     set status = 'POSTED', posted_at = now(), posted_by = v_owner, journal_entry_id = v_entry.journal_entry_id,
         cost_journal_entry_id = v_cost.journal_entry_id, invoice_no = 'INV-2026-00001', einvoice_status = 'NOT_SUBMITTED'
   where id = v_sale;
  update public.vehicles set status = 'SOLD' where id = v_sunny;

  perform set_config('app.tenant_id', '', true);
end
$$;

-- =============================================================================
-- Phase 5: an installment sale with papers (معرض النور).
--   Optra 2016 (cost 150,000) sold 2026-09-29 to عمر خالد for 200,000:
--   50,000 cash down + 6 monthly installments of 25,000 from 2026-09-30 (rule 13).
--   Installment 1 is already overdue; a post-dated cheque covers installment 2
--   and a promissory note installment 3. Cash 295,000 + 50,000 = 345,000.
-- =============================================================================
do $$
declare
  v_nour   constant uuid := '11111111-1111-1111-1111-111111111111';
  v_cash   constant uuid := 'c0000000-0000-0000-0000-000000000001';
  v_owner  constant uuid := 'a0000000-0000-0000-0000-000000000001';
  v_omar   constant uuid := 'd0000000-0000-0000-0000-000000000004';
  v_optra  constant uuid := 'e1000000-0000-0000-0000-000000000005';
  v_sale   constant uuid := 'd2000000-0000-0000-0000-000000000002';
  v_plan   constant uuid := 'd3000000-0000-0000-0000-000000000001';
  v_entry  record;
  v_cost   record;
  i        integer;
begin
  perform set_config('app.tenant_id', v_nour::text, true);
  insert into public.customers (id, tenant_id, name, phone_primary, is_buyer)
  values (v_omar, v_nour, 'عمر خالد', '+201005556677', true);

  update public.vehicles set status = 'AVAILABLE' where id = v_optra;
  update public.tenant_counters set last_value = 2 where tenant_id = v_nour and counter_key in ('sale-2026', 'invoice-2026');

  insert into public.sales (id, tenant_id, sale_no, vehicle_id, buyer_customer_id, sale_date, list_price, sale_price,
                            created_by, installment_plan)
  values (v_sale, v_nour, 'S-2026-0002', v_optra, v_omar, '2026-09-29', 200000.00, 200000.00, v_owner,
          '{"frequency": "MONTHLY", "count": 6, "first_due_date": "2026-09-30", "schedule": null}');
  insert into public.sale_payments (tenant_id, sale_id, cash_account_id, amount) values (v_nour, v_sale, v_cash, 50000.00);

  select * into v_entry from private.post_journal_entry(jsonb_build_object(
    'entry_date', '2026-09-29', 'description', 'بيع شيفروليه أوبترا 2016 إلى عمر خالد — S-2026-0002', 'source_type', 'SALE',
    'source_id', v_sale,
    'lines', jsonb_build_array(
      jsonb_build_object('ledger_account_id', (select ledger_account_id from public.cash_accounts where id = v_cash),
                         'debit', '50000.00', 'cash_account_id', v_cash),
      jsonb_build_object('ledger_account_id',
        (select id from public.ledger_accounts where tenant_id = v_nour and system_key = 'INSTALLMENT_RECEIVABLE'),
        'debit', '150000.00', 'customer_id', v_omar),
      jsonb_build_object('ledger_account_id',
        (select id from public.ledger_accounts where tenant_id = v_nour and system_key = 'VEHICLE_SALES'),
        'credit', '200000.00', 'vehicle_id', v_optra))));
  select * into v_cost from private.post_journal_entry(jsonb_build_object(
    'entry_date', '2026-09-29', 'description', 'تكلفة شيفروليه أوبترا 2016 — S-2026-0002', 'source_type', 'SALE_COST',
    'source_id', v_sale,
    'lines', jsonb_build_array(
      jsonb_build_object('ledger_account_id',
        (select id from public.ledger_accounts where tenant_id = v_nour and system_key = 'COST_OF_VEHICLES_SOLD'),
        'debit', '150000.00', 'vehicle_id', v_optra),
      jsonb_build_object('ledger_account_id',
        (select id from public.ledger_accounts where tenant_id = v_nour and system_key = 'VEHICLE_INVENTORY'),
        'credit', '150000.00', 'vehicle_id', v_optra))));
  update public.sales
     set status = 'POSTED', posted_at = now(), posted_by = v_owner, journal_entry_id = v_entry.journal_entry_id,
         cost_journal_entry_id = v_cost.journal_entry_id, invoice_no = 'INV-2026-00002',
         einvoice_status = 'NOT_SUBMITTED', receivable_amount = 150000.00
   where id = v_sale;
  update public.vehicles set status = 'SOLD' where id = v_optra;

  insert into public.installment_plans (id, tenant_id, sale_id, customer_id, financed_amount, frequency,
                                        installment_count, first_due_date)
  values (v_plan, v_nour, v_sale, v_omar, 150000.00, 'MONTHLY', 6, '2026-09-30');
  for i in 1..6 loop
    insert into public.installments (id, tenant_id, plan_id, seq, due_date, amount_due)
    values (('d4000000-0000-0000-0000-00000000000' || i)::uuid, v_nour, v_plan, i,
            ('2026-09-30'::date + make_interval(months => i - 1))::date, 25000.00);
  end loop;

  insert into public.deferred_papers (id, tenant_id, paper_type, number, customer_id, installment_id, amount, issue_date,
                                      due_date, storage_location, drawer_bank, drawer_branch, account_holder)
  values
    ('d5000000-0000-0000-0000-000000000001', v_nour, 'PDC', '004512', v_omar, 'd4000000-0000-0000-0000-000000000002',
     25000.00, '2026-09-29', '2026-10-30', 'الخزنة — ملف الشيكات', 'بنك مصر', 'فرع المعادي', 'عمر خالد'),
    ('d5000000-0000-0000-0000-000000000002', v_nour, 'PROMISSORY_NOTE', 'إ-0031', v_omar,
     'd4000000-0000-0000-0000-000000000003', 25000.00, '2026-09-29', '2026-11-30', 'الخزنة — ملف الإيصالات',
     null, null, null);
  insert into public.deferred_paper_events (tenant_id, paper_id, from_status, to_status, event_date)
  values (v_nour, 'd5000000-0000-0000-0000-000000000001', null, 'HELD', '2026-09-29'),
         (v_nour, 'd5000000-0000-0000-0000-000000000002', null, 'HELD', '2026-09-29');

  perform set_config('app.tenant_id', '', true);
end
$$;

-- =============================================================================
-- Phase 6: consignment and customer requests (معرض النور). No money moves.
--   Lancer 2017 consigned by سمير عادل on 2026-09-20, commission 5%,
--   expenses on the owner                                           AVAILABLE
--   External showroom معرض الأمل للسيارات (its yard is a location)
--   سارة إبراهيم asks for a Toyota Corolla 2018-2021 up to 650,000 -> matches
--   the Corolla in stock; a call-back is due since 2026-10-01
-- =============================================================================
do $$
declare
  v_nour    constant uuid := '11111111-1111-1111-1111-111111111111';
  v_owner   constant uuid := 'a0000000-0000-0000-0000-000000000001';
  v_sara    constant uuid := 'd0000000-0000-0000-0000-000000000003';
  v_samir   constant uuid := 'd0000000-0000-0000-0000-000000000005';
  v_lancer  constant uuid := 'e1000000-0000-0000-0000-000000000006';
  v_amal    constant uuid := 'd6000000-0000-0000-0000-000000000001';
  v_request constant uuid := 'd7000000-0000-0000-0000-000000000001';
begin
  perform set_config('app.tenant_id', v_nour::text, true);
  insert into public.customers (id, tenant_id, name, phone_primary, is_consignor)
  values (v_samir, v_nour, 'سمير عادل', '+201006667788', true);

  insert into public.vehicles (id, tenant_id, make, model, year, color_ext, transmission, fuel, mileage_km, plate_no,
                               asking_price, ownership_type, acquisition_source, stock_date, current_location_id)
  values (v_lancer, v_nour, 'Mitsubishi', 'Lancer', 2017, 'أزرق', 'AUTOMATIC', 'PETROL', 110000, 'ر ي ح 2468',
          310000.00, 'CONSIGNED_IN', 'CONSIGNMENT_IN', '2026-09-20',
          (select id from public.locations where tenant_id = v_nour and is_default));
  update public.vehicles set status = 'IN_PREPARATION' where id = v_lancer;
  update public.vehicles set status = 'AVAILABLE' where id = v_lancer;
  insert into public.consignments_in (id, tenant_id, vehicle_id, consignor_id, agreement_date, end_date, terms_type,
                                      commission_value, expenses_borne_by)
  values ('d8000000-0000-0000-0000-000000000001', v_nour, v_lancer, v_samir, '2026-09-20', '2026-12-20',
          'COMMISSION_PCT', 5, 'OWNER');

  insert into public.external_showrooms (id, tenant_id, name, contact_name, phone)
  values (v_amal, v_nour, 'معرض الأمل للسيارات', 'أ. مجدي', '+201007778899');
  insert into public.locations (tenant_id, type, name_ar, name_en, external_showroom_id)
  values (v_nour, 'EXTERNAL_SHOWROOM', 'معرض الأمل للسيارات', 'معرض الأمل للسيارات', v_amal);

  insert into public.customer_requests (id, tenant_id, customer_id, make, model, year_from, year_to, budget_max,
                                        assigned_to, source, created_by)
  values (v_request, v_nour, v_sara, 'Toyota', 'Corolla', 2018, 2021, 650000.00, v_owner, 'زيارة المعرض', v_owner);
  perform private.match_request(v_request);
  insert into public.follow_ups (tenant_id, customer_id, request_id, kind, occurred_at, result, notes,
                                 next_follow_up_date, assigned_to, priority, created_by)
  values (v_nour, v_sara, v_request, 'CALL', '2026-09-28 11:00+02', 'CALL_BACK', 'تريد معاينة الكورولا',
          '2026-10-01', v_owner, 'HIGH', v_owner);

  perform set_config('app.tenant_id', '', true);
end
$$;
