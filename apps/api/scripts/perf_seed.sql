-- Performance volume (BACKLOG 9.7, SPEC §11): one showroom with 5,000 vehicles
-- and about 100,000 journal lines, every entry posted through
-- private.post_journal_entry so the ledger rules hold. Local/staging only.
--   user: perf@sayyara.example / Demo-Pass-2026 (OWNER of "معرض الأداء")
-- Run: python scripts/perf_seed.py   (takes a few minutes)
do $$
declare
  v_tenant  constant uuid := '33333333-3333-3333-3333-333333333333';
  v_user    constant uuid := 'f0000000-0000-0000-0000-0000000000ff';
  v_cash    uuid := gen_random_uuid();
  v_bank    uuid := gen_random_uuid();
  v_cash_la uuid;
  v_bank_la uuid;
  v_inv     uuid;
  v_sales   uuid;
  v_cogs    uuid;
  v_equity  uuid;
  v_rent    uuid;
  v_util    uuid;
  v_cat     uuid;
  v_vehicle uuid;
  v_sale    uuid;
  v_entry   record;
  v_cost    record;
  v_day     date;
  v_price   numeric;
  v_today   date := (now() at time zone 'Africa/Cairo')::date;
  i         integer;
begin
  if exists (select 1 from public.tenants where id = v_tenant) then
    raise notice 'perf tenant already exists';
    return;
  end if;

  insert into auth.users (instance_id, id, aud, role, email, encrypted_password, email_confirmed_at,
                          raw_app_meta_data, raw_user_meta_data, created_at, updated_at,
                          confirmation_token, recovery_token, email_change, email_change_token_new)
  values ('00000000-0000-0000-0000-000000000000', v_user, 'authenticated', 'authenticated', 'perf@sayyara.example',
          extensions.crypt('Demo-Pass-2026', extensions.gen_salt('bf')), now(),
          '{"provider": "email", "providers": ["email"]}', '{"full_name": "Perf Owner"}', now(), now(), '', '', '', '');
  insert into auth.identities (id, user_id, provider_id, provider, identity_data, last_sign_in_at, created_at, updated_at)
  values (gen_random_uuid(), v_user, v_user::text, 'email',
          jsonb_build_object('sub', v_user, 'email', 'perf@sayyara.example', 'email_verified', true), now(), now(), now());

  insert into public.tenants (id, name_ar, name_en, country_code, currency_code, timezone)
  values (v_tenant, 'معرض الأداء', 'Performance Motors', 'EG', 'EGP', 'Africa/Cairo');
  insert into public.subscriptions (tenant_id, plan_id, status)
  select v_tenant, id, 'ACTIVE' from public.plans where code = 'STANDARD';
  insert into public.memberships (tenant_id, user_id, role_id)
  select v_tenant, v_user, id from public.roles where code = 'OWNER' and tenant_id is null;

  perform set_config('app.tenant_id', v_tenant::text, true);
  insert into public.ledger_accounts (tenant_id, code, parent_id, name_ar, name_en, type, normal_side, is_postable, subledger)
  values (v_tenant, '1101', (select id from public.ledger_accounts where tenant_id = v_tenant and code = '1100'),
          'الخزنة', 'Cash', 'ASSET', 'DEBIT', true, 'CASH_ACCOUNT') returning id into v_cash_la;
  insert into public.ledger_accounts (tenant_id, code, parent_id, name_ar, name_en, type, normal_side, is_postable, subledger)
  values (v_tenant, '1201', (select id from public.ledger_accounts where tenant_id = v_tenant and code = '1200'),
          'البنك', 'Bank', 'ASSET', 'DEBIT', true, 'CASH_ACCOUNT') returning id into v_bank_la;
  insert into public.cash_accounts (id, tenant_id, kind, name_ar, ledger_account_id, is_default)
  values (v_cash, v_tenant, 'CASH_BOX', 'الخزنة', v_cash_la, true), (v_bank, v_tenant, 'BANK', 'البنك', v_bank_la, false);

  select id into v_inv from public.ledger_accounts where tenant_id = v_tenant and system_key = 'VEHICLE_INVENTORY';
  select id into v_sales from public.ledger_accounts where tenant_id = v_tenant and system_key = 'VEHICLE_SALES';
  select id into v_cogs from public.ledger_accounts where tenant_id = v_tenant and system_key = 'COST_OF_VEHICLES_SOLD';
  select id into v_equity from public.ledger_accounts where tenant_id = v_tenant and system_key = 'OPENING_BALANCE_EQUITY';
  select id into v_rent from public.ledger_accounts where tenant_id = v_tenant and system_key = 'EXP_RENT';
  select id into v_util from public.ledger_accounts where tenant_id = v_tenant and system_key = 'EXP_UTILITIES';
  select id into v_cat from public.expense_categories where tenant_id = v_tenant and kind = 'VEHICLE' and code = 'maintenance';

  perform private.post_journal_entry(jsonb_build_object(
    'entry_date', (v_today - 420)::text, 'description', 'أرصدة افتتاحية', 'source_type', 'OPENING_BALANCE',
    'is_opening', true,
    'lines', jsonb_build_array(
      jsonb_build_object('ledger_account_id', v_bank_la, 'debit', '2000000000.00', 'cash_account_id', v_bank),
      jsonb_build_object('ledger_account_id', v_cash_la, 'debit', '500000000.00', 'cash_account_id', v_cash),
      jsonb_build_object('ledger_account_id', v_equity, 'credit', '2500000000.00'))));

  for i in 1..5000 loop
    v_day := v_today - 400 + (i % 400);
    v_price := 150000 + (i % 50) * 10000;
    insert into public.vehicles (tenant_id, make, model, year, color_ext, vin, asking_price, min_price, stock_date)
    values (v_tenant, (array['Toyota', 'Hyundai', 'Kia', 'Nissan', 'Chevrolet'])[1 + i % 5],
            (array['Corolla', 'Elantra', 'Cerato', 'Sunny', 'Optra', 'Tucson', 'Sportage'])[1 + i % 7],
            2012 + i % 13, 'أبيض', format('PERF%013s', i), v_price * 1.15, v_price * 1.08, v_day)
    returning id into v_vehicle;
    select * into v_entry from private.post_journal_entry(jsonb_build_object(
      'entry_date', v_day::text, 'description', format('شراء سيارة %s', i), 'source_type', 'VEHICLE_PURCHASE',
      'lines', jsonb_build_array(
        jsonb_build_object('ledger_account_id', v_inv, 'debit', v_price::text, 'vehicle_id', v_vehicle),
        jsonb_build_object('ledger_account_id', v_bank_la, 'credit', v_price::text, 'cash_account_id', v_bank))));
    insert into public.vehicle_purchases (tenant_id, vehicle_id, source, purchase_date, price, journal_entry_id)
    values (v_tenant, v_vehicle, 'OPENING', v_day, v_price, v_entry.journal_entry_id);
    for v_cost in select g from generate_series(1, 2) g loop
      select * into v_entry from private.post_journal_entry(jsonb_build_object(
        'entry_date', v_day::text, 'description', 'صيانة', 'source_type', 'VEHICLE_EXPENSE',
        'lines', jsonb_build_array(
          jsonb_build_object('ledger_account_id', v_inv, 'debit', '2500.00', 'vehicle_id', v_vehicle, 'memo', 'صيانة'),
          jsonb_build_object('ledger_account_id', v_cash_la, 'credit', '2500.00', 'cash_account_id', v_cash))));
      insert into public.vehicle_expenses (tenant_id, vehicle_id, category_id, expense_date, amount, funding,
                                           cash_account_id, treatment, journal_entry_id)
      values (v_tenant, v_vehicle, v_cat, v_day, 2500, 'CASH_ACCOUNT', v_cash, 'CAPITALIZE', v_entry.journal_entry_id);
    end loop;
    update public.vehicles set status = 'IN_PREPARATION' where id = v_vehicle;
    update public.vehicles set status = 'AVAILABLE' where id = v_vehicle;

    if i % 5 < 2 then  -- 2,000 sold
      v_day := least(v_day + 20 + i % 60, v_today);
      insert into public.sales (tenant_id, sale_no, vehicle_id, buyer_customer_id, sale_date, list_price, sale_price)
      select v_tenant, format('P-%s', i), v_vehicle, c.id, v_day, v_price * 1.15, v_price * 1.15
        from (select id from public.customers where tenant_id = v_tenant limit 1) c
      returning id into v_sale;
      if v_sale is null then
        insert into public.customers (tenant_id, name, phone_primary) values (v_tenant, 'عميل الأداء', '+201000000999');
        insert into public.sales (tenant_id, sale_no, vehicle_id, buyer_customer_id, sale_date, list_price, sale_price)
        select v_tenant, format('P-%s', i), v_vehicle, c.id, v_day, v_price * 1.15, v_price * 1.15
          from (select id from public.customers where tenant_id = v_tenant limit 1) c
        returning id into v_sale;
      end if;
      select * into v_entry from private.post_journal_entry(jsonb_build_object(
        'entry_date', v_day::text, 'description', format('بيع %s', i), 'source_type', 'SALE', 'source_id', v_sale,
        'lines', jsonb_build_array(
          jsonb_build_object('ledger_account_id', v_cash_la, 'debit', (v_price * 1.15)::text, 'cash_account_id', v_cash),
          jsonb_build_object('ledger_account_id', v_sales, 'credit', (v_price * 1.15)::text, 'vehicle_id', v_vehicle))));
      select * into v_cost from private.post_journal_entry(jsonb_build_object(
        'entry_date', v_day::text, 'description', format('تكلفة %s', i), 'source_type', 'SALE_COST', 'source_id', v_sale,
        'lines', jsonb_build_array(
          jsonb_build_object('ledger_account_id', v_cogs, 'debit', (v_price + 5000)::text, 'vehicle_id', v_vehicle),
          jsonb_build_object('ledger_account_id', v_inv, 'credit', (v_price + 5000)::text, 'vehicle_id', v_vehicle))));
      update public.sales set status = 'POSTED', posted_at = now(), journal_entry_id = v_entry.journal_entry_id,
             cost_journal_entry_id = v_cost.journal_entry_id, invoice_no = format('PI-%s', i)
       where id = v_sale;
      update public.vehicles set status = 'SOLD' where id = v_vehicle;
      v_sale := null;
    end if;
  end loop;

  -- General expenses to reach about 100,000 journal lines.
  for i in 1..31000 loop
    perform private.post_journal_entry(jsonb_build_object(
      'entry_date', (v_today - (i % 400))::text, 'description', 'مصروف عام', 'source_type', 'GENERAL_EXPENSE',
      'lines', jsonb_build_array(
        jsonb_build_object('ledger_account_id', case when i % 2 = 0 then v_rent else v_util end, 'debit', '100.00'),
        jsonb_build_object('ledger_account_id', v_cash_la, 'credit', '100.00', 'cash_account_id', v_cash))));
  end loop;
  perform set_config('app.tenant_id', '', true);
end
$$;
