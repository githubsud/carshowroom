-- Pilot review 3 (D-134): a car a little above the customer's ceiling is still
-- suggested; a car corrected while available is matched; suggestions that no longer fit are dropped unless already contacted.
begin;
set local search_path = public, extensions;
select plan(9);

insert into auth.users (id, email, aud, role, instance_id) values
  ('00000000-0000-0000-0000-0000000f3001', 'r3-owner@test.local', 'authenticated', 'authenticated', '00000000-0000-0000-0000-000000000000');
insert into public.tenants (id, name_ar, country_code, currency_code, timezone) values
  ('f3000000-0000-0000-0000-0000000000aa', 'معرض الطلبات', 'EG', 'EGP', 'Africa/Cairo');
insert into public.memberships (tenant_id, user_id, role_id)
select 'f3000000-0000-0000-0000-0000000000aa', '00000000-0000-0000-0000-0000000f3001', r.id
  from public.roles r where r.code = 'OWNER' and r.tenant_id is null;

select is(
  (select request_budget_tolerance_pct from public.tenant_settings where tenant_id = 'f3000000-0000-0000-0000-0000000000aa'),
  10.00::numeric, 'a showroom suggests cars up to 10% above the customer''s budget by default'
);

insert into public.customers (id, tenant_id, name, phone_primary) values
  ('f3c00000-0000-0000-0000-000000000001', 'f3000000-0000-0000-0000-0000000000aa', 'عميل باترول', '+201000000301');
-- The pilot's case: a Patrol 2015-2022 for 300,000 to 600,000.
insert into public.customer_requests (id, tenant_id, customer_id, make, model, year_from, year_to, budget_min, budget_max)
values ('f3a00000-0000-0000-0000-000000000001', 'f3000000-0000-0000-0000-0000000000aa',
        'f3c00000-0000-0000-0000-000000000001', 'نيسان', 'باترول', 2015, 2022, 300000, 600000);

-- Put on sale at 650,000 (8% above the ceiling) and 700,000 (17% above).
insert into public.vehicles (id, tenant_id, make, model, year, asking_price, ownership_type) values
  ('f3e00000-0000-0000-0000-000000000001', 'f3000000-0000-0000-0000-0000000000aa', 'Nissan', 'باترول', 2021, 650000, 'OWNED'),
  ('f3e00000-0000-0000-0000-000000000002', 'f3000000-0000-0000-0000-0000000000aa', 'نيسان', 'باترول', 2020, 700000, 'OWNED');
update public.vehicles set status = 'IN_PREPARATION'
 where id in ('f3e00000-0000-0000-0000-000000000001', 'f3e00000-0000-0000-0000-000000000002');
update public.vehicles set status = 'AVAILABLE'
 where id in ('f3e00000-0000-0000-0000-000000000001', 'f3e00000-0000-0000-0000-000000000002');
select results_eq(
  $$ select vehicle_id from public.customer_request_matches where request_id = 'f3a00000-0000-0000-0000-000000000001' $$,
  $$ values ('f3e00000-0000-0000-0000-000000000001'::uuid) $$,
  'a car slightly above the budget is matched, within the tolerance but not beyond it'
);
select is(
  (select count(*)::int from public.notifications where kind = 'REQUEST_MATCH'
    and entity_id = 'f3e00000-0000-0000-0000-000000000001'),
  1, 'the owner is told a customer asked for the car'
);

update public.vehicles set asking_price = 640000 where id = 'f3e00000-0000-0000-0000-000000000002';
select ok(
  exists (select 1 from public.customer_request_matches where vehicle_id = 'f3e00000-0000-0000-0000-000000000002'),
  'lowering the price of an available car matches it'
);

update public.vehicles set asking_price = 800000 where id = 'f3e00000-0000-0000-0000-000000000002';
select ok(
  not exists (select 1 from public.customer_request_matches where vehicle_id = 'f3e00000-0000-0000-0000-000000000002'),
  'a suggestion that no longer fits is dropped'
);

update public.customer_request_matches set contacted = true where vehicle_id = 'f3e00000-0000-0000-0000-000000000001';
update public.vehicles set asking_price = 900000 where id = 'f3e00000-0000-0000-0000-000000000001';
select ok(
  exists (select 1 from public.customer_request_matches where vehicle_id = 'f3e00000-0000-0000-0000-000000000001'),
  'a car the customer was already told about stays on the request'
);

-- Editing the request: a higher budget brings the 800,000 car in.
update public.customer_requests set budget_max = 750000 where id = 'f3a00000-0000-0000-0000-000000000001';
select is(private.match_request('f3a00000-0000-0000-0000-000000000001'), 1, 'a raised budget finds the car');

-- Tolerance 0: only cars within the budget itself.
update public.tenant_settings set request_budget_tolerance_pct = 0 where tenant_id = 'f3000000-0000-0000-0000-0000000000aa';
select ok(
  not exists (select 1 from public.customer_request_matches where vehicle_id = 'f3e00000-0000-0000-0000-000000000002'),
  'changing the tolerance re-checks the open requests'
);

select throws_ok(
  $$ update public.tenant_settings set request_budget_tolerance_pct = 60
      where tenant_id = 'f3000000-0000-0000-0000-0000000000aa' $$,
  '23514', null, 'the tolerance is at most 50%'
);

select * from finish();
rollback;
