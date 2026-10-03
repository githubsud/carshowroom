-- Consignment and CRM (SPEC §4.4-§4.6): agreements are consistent, the journal
-- subledgers point at real consignors and showrooms, a car becoming AVAILABLE
-- is matched against open requests with an alert, and logged calls never change.
begin;
set local search_path = public, extensions;
select plan(12);

insert into auth.users (id, email, aud, role, instance_id) values
  ('00000000-0000-0000-0000-0000000ae001', 'c-owner@test.local', 'authenticated', 'authenticated', '00000000-0000-0000-0000-000000000000');
insert into public.tenants (id, name_ar, country_code, currency_code, timezone) values
  ('aaaaaaaa-0000-0000-0000-0000000000aa', 'معرض الأمانات', 'EG', 'EGP', 'Africa/Cairo');
insert into public.memberships (tenant_id, user_id, role_id)
select 'aaaaaaaa-0000-0000-0000-0000000000aa', '00000000-0000-0000-0000-0000000ae001', r.id
  from public.roles r where r.code = 'OWNER' and r.tenant_id is null;

select is(
  (select p.code from public.ledger_accounts a join public.ledger_accounts p on p.id = a.parent_id
    where a.tenant_id = 'aaaaaaaa-0000-0000-0000-0000000000aa' and a.system_key = 'EXP_CONSIGNMENT'),
  '6200',
  'a new showroom gets the consigned-car expense account (P-05) under general expenses'
);

insert into public.customers (id, tenant_id, name, phone_primary) values
  ('ce000000-0000-0000-0000-000000000001', 'aaaaaaaa-0000-0000-0000-0000000000aa', 'سمير', '+201000000001'),
  ('ce000000-0000-0000-0000-000000000002', 'aaaaaaaa-0000-0000-0000-0000000000aa', 'عميل يبحث', '+201000000002');
insert into public.vehicles (id, tenant_id, make, model, year, asking_price, ownership_type) values
  ('ae000000-0000-0000-0000-000000000001', 'aaaaaaaa-0000-0000-0000-0000000000aa', 'Kia', 'Cerato', 2021, 300000, 'CONSIGNED_IN'),
  ('ae000000-0000-0000-0000-000000000002', 'aaaaaaaa-0000-0000-0000-0000000000aa', 'Toyota', 'Corolla XLi', 2020, 400000, 'OWNED'),
  ('ae000000-0000-0000-0000-000000000003', 'aaaaaaaa-0000-0000-0000-0000000000aa', 'Toyota', 'Corolla', 2020, 900000, 'OWNED');

-- --- Agreements -------------------------------------------------------------------------------
select throws_ok(
  $$ insert into public.consignments_in (tenant_id, vehicle_id, consignor_id, agreement_date, terms_type, commission_value)
     values ('aaaaaaaa-0000-0000-0000-0000000000aa', 'ae000000-0000-0000-0000-000000000001',
             'ce000000-0000-0000-0000-000000000001', current_date, 'NET_PRICE', 5) $$,
  '23514', null, 'net-price terms need the net price, not a commission'
);
select throws_ok(
  $$ insert into public.consignments_in (tenant_id, vehicle_id, consignor_id, agreement_date, terms_type, commission_value,
                                         expenses_borne_by)
     values ('aaaaaaaa-0000-0000-0000-0000000000aa', 'ae000000-0000-0000-0000-000000000001',
             'ce000000-0000-0000-0000-000000000001', current_date, 'COMMISSION_PCT', 5, 'SHARED') $$,
  '23514', null, 'shared expenses need the owner''s percentage'
);
select lives_ok(
  $$ insert into public.consignments_in (id, tenant_id, vehicle_id, consignor_id, agreement_date, terms_type, commission_value)
     values ('af000000-0000-0000-0000-000000000001', 'aaaaaaaa-0000-0000-0000-0000000000aa',
             'ae000000-0000-0000-0000-000000000001', 'ce000000-0000-0000-0000-000000000001', current_date,
             'COMMISSION_PCT', 5) $$,
  'a percentage agreement is accepted'
);
select throws_ok(
  $$ insert into public.consignments_in (tenant_id, vehicle_id, consignor_id, agreement_date, terms_type, commission_value)
     values ('aaaaaaaa-0000-0000-0000-0000000000aa', 'ae000000-0000-0000-0000-000000000001',
             'ce000000-0000-0000-0000-000000000001', current_date, 'COMMISSION_FIXED', 1000) $$,
  '23505', null, 'a car has one consignment agreement (Q-33)'
);

-- --- Subledgers ---------------------------------------------------------------------------------
select set_config('app.tenant_id', 'aaaaaaaa-0000-0000-0000-0000000000aa', true);
select throws_ok(
  $$ select private.post_journal_entry(jsonb_build_object(
       'entry_date', current_date, 'description', 'test', 'source_type', 'TEST',
       'lines', jsonb_build_array(
         jsonb_build_object('ledger_account_id',
           (select id from public.ledger_accounts where tenant_id = 'aaaaaaaa-0000-0000-0000-0000000000aa' and system_key = 'CONSIGNOR_RECOVERABLE'),
           'consignor_id', gen_random_uuid(), 'debit', '10.00'),
         jsonb_build_object('ledger_account_id',
           (select id from public.ledger_accounts where tenant_id = 'aaaaaaaa-0000-0000-0000-0000000000aa' and system_key = 'OPENING_BALANCE_EQUITY'),
           'credit', '10.00')))) $$,
  '23503', null, 'a consignor subledger line must name a real customer'
);

-- --- Matching ----------------------------------------------------------------------------------
insert into public.customer_requests (id, tenant_id, customer_id, make, model, year_from, year_to, budget_max) values
  ('a7000000-0000-0000-0000-000000000001', 'aaaaaaaa-0000-0000-0000-0000000000aa', 'ce000000-0000-0000-0000-000000000002',
   'toyota', 'corolla', 2018, 2021, 450000);
update public.vehicles set status = 'IN_PREPARATION' where id in ('ae000000-0000-0000-0000-000000000002', 'ae000000-0000-0000-0000-000000000003');
select is(
  (select count(*)::int from public.customer_request_matches where request_id = 'a7000000-0000-0000-0000-000000000001'),
  0, 'a car in preparation is not matched'
);
update public.vehicles set status = 'AVAILABLE' where id in ('ae000000-0000-0000-0000-000000000002', 'ae000000-0000-0000-0000-000000000003');
select results_eq(
  $$ select vehicle_id from public.customer_request_matches where request_id = 'a7000000-0000-0000-0000-000000000001' $$,
  $$ values ('ae000000-0000-0000-0000-000000000002'::uuid) $$,
  'becoming AVAILABLE matches make and model (any case), year range and budget ceiling'
);
select is(
  (select (params ->> 'count')::int from public.notifications
    where tenant_id = 'aaaaaaaa-0000-0000-0000-0000000000aa' and kind = 'REQUEST_MATCH'
      and entity_id = 'ae000000-0000-0000-0000-000000000002'),
  1, 'members who manage requests are told how many customers asked for the car'
);
update public.vehicles set status = 'AVAILABLE', asking_price = 420000 where id = 'ae000000-0000-0000-0000-000000000002';
select is(
  (select count(*)::int from public.notifications where kind = 'REQUEST_MATCH'
    and entity_id = 'ae000000-0000-0000-0000-000000000002'),
  1, 'no new alert without a new match'
);
update public.customer_requests set status = 'WON' where id = 'a7000000-0000-0000-0000-000000000001';
select is(
  private.match_request('a7000000-0000-0000-0000-000000000001'), 0, 'a closed request is not matched'
);

-- --- Follow-ups --------------------------------------------------------------------------------
insert into public.follow_ups (id, tenant_id, customer_id, result) values
  ('a8000000-0000-0000-0000-000000000001', 'aaaaaaaa-0000-0000-0000-0000000000aa', 'ce000000-0000-0000-0000-000000000002', 'ANSWERED');
select throws_ok(
  $$ delete from public.follow_ups where id = 'a8000000-0000-0000-0000-000000000001' $$,
  'SR003', null, 'a logged call cannot be deleted'
);

select * from finish();
rollback;
