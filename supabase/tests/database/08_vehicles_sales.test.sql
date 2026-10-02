-- Vehicles and sales (SPEC §4.3, §4.7, §10): the status lifecycle and business
-- rule 1 hold in the database, history is append-only, and sales staff never
-- reach cost data through the Supabase client.
begin;
set local search_path = public, extensions;
select plan(21);

insert into auth.users (id, email, aud, role, instance_id) values
  ('00000000-0000-0000-0000-0000000ac001', 'v-owner@test.local', 'authenticated', 'authenticated', '00000000-0000-0000-0000-000000000000'),
  ('00000000-0000-0000-0000-0000000ac002', 'v-sales@test.local', 'authenticated', 'authenticated', '00000000-0000-0000-0000-000000000000');

insert into public.tenants (id, name_ar, country_code, currency_code, timezone) values
  ('aaaaaaaa-0000-0000-0000-0000000000a8', 'معرض السيارات', 'EG', 'EGP', 'Africa/Cairo'),
  ('bbbbbbbb-0000-0000-0000-0000000000b8', 'معرض آخر', 'EG', 'EGP', 'Africa/Cairo');

insert into public.memberships (tenant_id, user_id, role_id)
select 'aaaaaaaa-0000-0000-0000-0000000000a8', u.user_id::uuid, r.id
  from (values ('00000000-0000-0000-0000-0000000ac001', 'OWNER'), ('00000000-0000-0000-0000-0000000ac002', 'SALES'))
       as u (user_id, role_code)
  join public.roles r on r.code = u.role_code and r.tenant_id is null;

insert into public.customers (id, tenant_id, name) values
  ('cc000000-0000-0000-0000-000000000001', 'aaaaaaaa-0000-0000-0000-0000000000a8', 'حسن'),
  ('cc000000-0000-0000-0000-000000000002', 'bbbbbbbb-0000-0000-0000-0000000000b8', 'عميل آخر');

-- --- Stock number, VIN, initial status ------------------------------------------------
insert into public.vehicles (id, tenant_id, make, model, year, vin, asking_price, min_price) values
  ('ae000000-0000-0000-0000-000000000001', 'aaaaaaaa-0000-0000-0000-0000000000a8', 'Hyundai', 'Elantra', 2019,
   'kmh-dn41a 2ku123456', 480000, 460000);

select matches(
  (select stock_no from public.vehicles where id = 'ae000000-0000-0000-0000-000000000001'),
  '^V-[0-9]{4}-0001$',
  'the first vehicle gets stock number V-YYYY-0001'
);
select is(
  (select vin_normalized from public.vehicles where id = 'ae000000-0000-0000-0000-000000000001'),
  'KMHDN41A2KU123456',
  'the VIN is normalised (upper case, no spaces or dashes)'
);
select throws_ok(
  $$ insert into public.vehicles (tenant_id, make, model, status) values
       ('aaaaaaaa-0000-0000-0000-0000000000a8', 'Kia', 'Rio', 'AVAILABLE') $$,
  'SR020', null,
  'a vehicle always starts as DRAFT'
);
select throws_ok(
  $$ insert into public.vehicles (tenant_id, make, model, vin) values
       ('aaaaaaaa-0000-0000-0000-0000000000a8', 'Hyundai', 'Elantra', 'KMHDN41A2KU123456') $$,
  '23505', null,
  'the same VIN cannot be in stock twice'
);

-- --- State machine ----------------------------------------------------------------------
select throws_ok(
  $$ update public.vehicles set status = 'SOLD' where id = 'ae000000-0000-0000-0000-000000000001' $$,
  'SR020', null,
  'DRAFT cannot jump to SOLD'
);
update public.vehicles set status = 'IN_PREPARATION' where id = 'ae000000-0000-0000-0000-000000000001';
update public.vehicles set status = 'AVAILABLE' where id = 'ae000000-0000-0000-0000-000000000001';
select results_eq(
  $$ select from_status, to_status from public.vehicle_status_history
      where vehicle_id = 'ae000000-0000-0000-0000-000000000001' order by changed_at, from_status nulls first $$,
  $$ values (null::text, 'DRAFT'::text), ('DRAFT', 'IN_PREPARATION'), ('IN_PREPARATION', 'AVAILABLE') $$,
  'every status change is recorded'
);
select throws_ok(
  $$ update public.vehicles set status = 'SOLD' where id = 'ae000000-0000-0000-0000-000000000001' $$,
  'SR020', null,
  'AVAILABLE -> SOLD needs a posted sale'
);
select throws_ok(
  $$ update public.vehicles set status = 'RETURNED_TO_OWNER' where id = 'ae000000-0000-0000-0000-000000000001' $$,
  'SR020', null,
  'only a consigned-in car can be returned to its owner'
);
select throws_ok(
  $$ update public.vehicles set stock_no = 'V-1999-0001' where id = 'ae000000-0000-0000-0000-000000000001' $$,
  'SR003', null,
  'the stock number never changes'
);

-- --- Price history -------------------------------------------------------------------------
update public.vehicles set asking_price = 470000 where id = 'ae000000-0000-0000-0000-000000000001';
select is(
  (select array_agg(asking_price order by changed_at, asking_price desc) from public.vehicle_price_history
    where vehicle_id = 'ae000000-0000-0000-0000-000000000001'),
  array[480000.00, 470000.00]::numeric[],
  'price changes are kept'
);
select throws_ok(
  $$ delete from public.vehicle_price_history where vehicle_id = 'ae000000-0000-0000-0000-000000000001' $$,
  'SR003', null,
  'history cannot be deleted'
);

-- --- Business rule 1: sold once ------------------------------------------------------------
select set_config('app.tenant_id', 'aaaaaaaa-0000-0000-0000-0000000000a8', true);
create temporary table posted on commit drop as
select journal_entry_id, entry_no from private.post_journal_entry(jsonb_build_object(
  'entry_date', current_date, 'description', 'test', 'source_type', 'TEST',
  'lines', jsonb_build_array(
    jsonb_build_object('ledger_account_id',
      (select id from public.ledger_accounts where tenant_id = 'aaaaaaaa-0000-0000-0000-0000000000a8' and system_key = 'VEHICLE_INVENTORY'),
      'vehicle_id', 'ae000000-0000-0000-0000-000000000001', 'debit', '400000.00'),
    jsonb_build_object('ledger_account_id',
      (select id from public.ledger_accounts where tenant_id = 'aaaaaaaa-0000-0000-0000-0000000000a8' and system_key = 'OPENING_BALANCE_EQUITY'),
      'credit', '400000.00'))));

insert into public.sales (id, tenant_id, sale_no, vehicle_id, buyer_customer_id, sale_date, list_price, sale_price,
                          status, posted_at, journal_entry_id, cost_journal_entry_id, invoice_no)
select 'ab000000-0000-0000-0000-000000000001', 'aaaaaaaa-0000-0000-0000-0000000000a8', 'S-1',
       'ae000000-0000-0000-0000-000000000001', 'cc000000-0000-0000-0000-000000000001', current_date, 470000, 470000,
       'POSTED', now(), journal_entry_id, journal_entry_id, 'INV-1'
  from posted;
select lives_ok(
  $$ update public.vehicles set status = 'SOLD' where id = 'ae000000-0000-0000-0000-000000000001' $$,
  'with a posted sale the vehicle becomes SOLD'
);
select throws_ok(
  $$ insert into public.sales (tenant_id, sale_no, vehicle_id, buyer_customer_id, sale_date, list_price, sale_price,
                               status, posted_at, journal_entry_id, cost_journal_entry_id, invoice_no)
     select 'aaaaaaaa-0000-0000-0000-0000000000a8', 'S-2', 'ae000000-0000-0000-0000-000000000001',
            'cc000000-0000-0000-0000-000000000001', current_date, 500000, 500000, 'POSTED', now(),
            journal_entry_id, journal_entry_id, 'INV-2' from posted $$,
  '23505', null,
  'a vehicle cannot have two posted sales'
);
select throws_ok(
  $$ update public.sales set sale_price = 1, list_price = 1 where id = 'ab000000-0000-0000-0000-000000000001' $$,
  'SR003', null,
  'a posted sale cannot be edited'
);
select throws_ok(
  $$ delete from public.sales where id = 'ab000000-0000-0000-0000-000000000001' $$,
  'SR003', null,
  'a posted sale cannot be deleted'
);
select throws_ok(
  $$ update public.vehicles set status = 'AVAILABLE' where id = 'ae000000-0000-0000-0000-000000000001' $$,
  'SR020', null,
  'a sold vehicle returns to stock only after its sale is cancelled'
);

-- --- Tenant isolation through foreign keys -------------------------------------------------
select throws_ok(
  $$ insert into public.reservations (tenant_id, vehicle_id, customer_id, reservation_date, deposit_amount,
                                      cash_account_id, journal_entry_id)
     select 'aaaaaaaa-0000-0000-0000-0000000000a8', 'ae000000-0000-0000-0000-000000000001',
            'cc000000-0000-0000-0000-000000000002', current_date, 1000, gen_random_uuid(), journal_entry_id from posted $$,
  '23503', null,
  'a reservation cannot point at another showroom''s customer'
);

-- --- Cost masking for sales staff (SPEC §10) ------------------------------------------------
insert into public.documents (tenant_id, entity_type, entity_id, doc_type, storage_path, file_name, content_type,
                              size_bytes, sensitivity) values
  ('aaaaaaaa-0000-0000-0000-0000000000a8', 'VEHICLE', 'ae000000-0000-0000-0000-000000000001', 'LICENSE',
   'aaaaaaaa/license.pdf', 'license.pdf', 'application/pdf', 100, 'NORMAL'),
  ('aaaaaaaa-0000-0000-0000-0000000000a8', 'VEHICLE', 'ae000000-0000-0000-0000-000000000001', 'PURCHASE_CONTRACT',
   'aaaaaaaa/contract.pdf', 'contract.pdf', 'application/pdf', 100, 'COST');
select throws_ok(
  $$ insert into public.documents (tenant_id, entity_type, entity_id, doc_type, storage_path, file_name, content_type,
                                   size_bytes, sensitivity) values
       ('aaaaaaaa-0000-0000-0000-0000000000a8', 'VEHICLE', 'ae000000-0000-0000-0000-000000000001', 'SELLER_RECEIPT',
        'aaaaaaaa/receipt.pdf', 'receipt.pdf', 'application/pdf', 100, 'NORMAL') $$,
  '23514', null,
  'a seller receipt is always cost-sensitive'
);

select hasnt_column('public', 'vehicles_catalog', 'min_price', 'the catalog view has no minimum price');

set local role authenticated;
select set_config('request.jwt.claims', '{"sub": "00000000-0000-0000-0000-0000000ac002", "role": "authenticated"}', true);
select results_eq(
  $$ select (select count(*) from public.vehicles), (select count(*) from public.vehicles_catalog),
            (select count(*) from public.vehicle_price_history), (select count(*) from public.journal_lines) $$,
  $$ values (0::bigint, 1::bigint, 0::bigint, 0::bigint) $$,
  'sales staff read vehicles only through the catalog, and no prices history or ledger lines'
);
select results_eq(
  $$ select doc_type from public.documents $$,
  $$ values ('LICENSE'::text) $$,
  'sales staff do not see cost documents'
);

select * from finish();
rollback;
