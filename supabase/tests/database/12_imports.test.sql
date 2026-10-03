-- Imports (SPEC §4.13): a committed import never changes; an imported plan has
-- an opening reference instead of a sale; only an OPENING purchase may have no seller.
begin;
set local search_path = public, extensions;
select plan(5);

insert into public.tenants (id, name_ar, country_code, currency_code, timezone) values
  ('aaaaaaaa-0000-0000-0000-0000000000ac', 'معرض الاستيراد', 'EG', 'EGP', 'Africa/Cairo');
insert into public.customers (id, tenant_id, name) values
  ('ce100000-0000-0000-0000-000000000001', 'aaaaaaaa-0000-0000-0000-0000000000ac', 'مريم');

select throws_ok(
  $$ insert into public.installment_plans (tenant_id, customer_id, financed_amount, frequency, installment_count, first_due_date)
     values ('aaaaaaaa-0000-0000-0000-0000000000ac', 'ce100000-0000-0000-0000-000000000001', 100, 'MANUAL', 1, current_date) $$,
  '23514', null, 'a plan has a sale or an opening reference'
);
select lives_ok(
  $$ insert into public.installment_plans (tenant_id, customer_id, financed_amount, frequency, installment_count,
                                          first_due_date, opening_reference)
     values ('aaaaaaaa-0000-0000-0000-0000000000ac', 'ce100000-0000-0000-0000-000000000001', 100, 'MANUAL', 1,
             current_date, 'C-1') $$,
  'an imported plan carries its opening reference'
);

insert into public.import_jobs (id, tenant_id, go_live_date, sheets, status, committed_at)
values ('a1000000-0000-0000-0000-0000000000ac', 'aaaaaaaa-0000-0000-0000-0000000000ac', current_date, '[]',
        'COMMITTED', now());
select throws_ok(
  $$ update public.import_jobs set sheets = '[{}]' where id = 'a1000000-0000-0000-0000-0000000000ac' $$,
  'SR003', null, 'a committed import never changes'
);

select throws_ok(
  $$ insert into public.vehicle_purchases (tenant_id, vehicle_id, source, purchase_date, price, journal_entry_id)
     values ('aaaaaaaa-0000-0000-0000-0000000000ac', gen_random_uuid(), 'PURCHASE', current_date, 1, gen_random_uuid()) $$,
  '23514', null, 'a purchase names its seller'
);
select is(
  (select count(*)::int from pg_constraint where conname = 'vehicle_purchases_seller'),
  1, 'opening purchases may omit the seller'
);

select * from finish();
rollback;
