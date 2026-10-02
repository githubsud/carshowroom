-- Installments (SPEC §4.8): schedules are fixed once created, remaining is
-- derived and ignores bounced receipts, papers follow their status machine,
-- and a user sees only their own notifications.
begin;
set local search_path = public, extensions;
select plan(13);

insert into auth.users (id, email, aud, role, instance_id) values
  ('00000000-0000-0000-0000-0000000ad001', 'i-owner@test.local', 'authenticated', 'authenticated', '00000000-0000-0000-0000-000000000000'),
  ('00000000-0000-0000-0000-0000000ad002', 'i-other@test.local', 'authenticated', 'authenticated', '00000000-0000-0000-0000-000000000000');
insert into public.tenants (id, name_ar, country_code, currency_code, timezone) values
  ('aaaaaaaa-0000-0000-0000-0000000000a9', 'معرض الأقساط', 'EG', 'EGP', 'Africa/Cairo');
insert into public.memberships (tenant_id, user_id, role_id)
select 'aaaaaaaa-0000-0000-0000-0000000000a9', u.user_id::uuid, r.id
  from (values ('00000000-0000-0000-0000-0000000ad001'), ('00000000-0000-0000-0000-0000000ad002')) as u (user_id)
  join public.roles r on r.code = 'OWNER' and r.tenant_id is null;

select is(
  (select p.code from public.ledger_accounts a join public.ledger_accounts p on p.id = a.parent_id
    where a.tenant_id = 'aaaaaaaa-0000-0000-0000-0000000000a9' and a.system_key = 'EXP_BANK_CHARGES'),
  '6200',
  'a new showroom gets the bank charges account (P-07) under general expenses'
);

insert into public.customers (id, tenant_id, name) values
  ('cd000000-0000-0000-0000-000000000001', 'aaaaaaaa-0000-0000-0000-0000000000a9', 'مريم');
insert into public.vehicles (id, tenant_id, make, model) values
  ('ad000000-0000-0000-0000-000000000001', 'aaaaaaaa-0000-0000-0000-0000000000a9', 'Kia', 'Cerato');

select set_config('app.tenant_id', 'aaaaaaaa-0000-0000-0000-0000000000a9', true);
create temporary table posted on commit drop as
select journal_entry_id from private.post_journal_entry(jsonb_build_object(
  'entry_date', current_date, 'description', 'test', 'source_type', 'TEST',
  'lines', jsonb_build_array(
    jsonb_build_object('ledger_account_id',
      (select id from public.ledger_accounts where tenant_id = 'aaaaaaaa-0000-0000-0000-0000000000a9' and system_key = 'INSTALLMENT_RECEIVABLE'),
      'customer_id', 'cd000000-0000-0000-0000-000000000001', 'debit', '1000.00'),
    jsonb_build_object('ledger_account_id',
      (select id from public.ledger_accounts where tenant_id = 'aaaaaaaa-0000-0000-0000-0000000000a9' and system_key = 'OPENING_BALANCE_EQUITY'),
      'credit', '1000.00'))));

insert into public.sales (id, tenant_id, sale_no, vehicle_id, buyer_customer_id, sale_date, list_price, sale_price)
values ('ac000000-0000-0000-0000-000000000001', 'aaaaaaaa-0000-0000-0000-0000000000a9', 'S-1',
        'ad000000-0000-0000-0000-000000000001', 'cd000000-0000-0000-0000-000000000001', current_date, 1000, 1000);
insert into public.installment_plans (id, tenant_id, sale_id, customer_id, financed_amount, frequency, installment_count,
                                      first_due_date)
values ('a1000000-0000-0000-0000-000000000001', 'aaaaaaaa-0000-0000-0000-0000000000a9',
        'ac000000-0000-0000-0000-000000000001', 'cd000000-0000-0000-0000-000000000001', 1000, 'MONTHLY', 2,
        current_date);
insert into public.installments (id, tenant_id, plan_id, seq, due_date, amount_due) values
  ('a2000000-0000-0000-0000-000000000001', 'aaaaaaaa-0000-0000-0000-0000000000a9', 'a1000000-0000-0000-0000-000000000001', 1, current_date, 500),
  ('a2000000-0000-0000-0000-000000000002', 'aaaaaaaa-0000-0000-0000-0000000000a9', 'a1000000-0000-0000-0000-000000000001', 2, current_date + 30, 500);

-- --- Fixed schedule -----------------------------------------------------------------------
select throws_ok(
  $$ update public.installments set amount_due = 1 where id = 'a2000000-0000-0000-0000-000000000001' $$,
  'SR003', null, 'an installment cannot be edited'
);
select throws_ok(
  $$ delete from public.installments where id = 'a2000000-0000-0000-0000-000000000002' $$,
  'SR003', null, 'an installment cannot be deleted'
);
select throws_ok(
  $$ update public.installment_plans set financed_amount = 1 where id = 'a1000000-0000-0000-0000-000000000001' $$,
  'SR003', null, 'a plan cannot be edited'
);

-- --- Remaining is derived and ignores bounced receipts ---------------------------------------
select throws_ok(
  $$ insert into public.customer_receipts (tenant_id, customer_id, plan_id, receipt_date, amount, source, journal_entry_id)
     select 'aaaaaaaa-0000-0000-0000-0000000000a9', 'cd000000-0000-0000-0000-000000000001',
            'a1000000-0000-0000-0000-000000000001', current_date, 300, 'CASH_ACCOUNT', journal_entry_id from posted $$,
  '23514', null, 'a cash receipt names its cash account'
);
insert into public.customer_receipts (id, tenant_id, customer_id, plan_id, receipt_date, amount, source, journal_entry_id)
select 'a3000000-0000-0000-0000-000000000002', 'aaaaaaaa-0000-0000-0000-0000000000a9',
       'cd000000-0000-0000-0000-000000000001', 'a1000000-0000-0000-0000-000000000001', current_date, 300, 'CREDIT',
       journal_entry_id from posted;
insert into public.installment_payments (tenant_id, receipt_id, installment_id, amount) values
  ('aaaaaaaa-0000-0000-0000-0000000000a9', 'a3000000-0000-0000-0000-000000000002', 'a2000000-0000-0000-0000-000000000001', 300);
select results_eq(
  $$ select paid, remaining from public.installment_status where id = 'a2000000-0000-0000-0000-000000000001' $$,
  $$ values (300.00::numeric(18, 2), 200.00::numeric(18, 2)) $$,
  'paid and remaining are derived from allocations'
);
update public.customer_receipts set status = 'BOUNCED', bounce_entry_id = (select journal_entry_id from posted)
 where id = 'a3000000-0000-0000-0000-000000000002';
select results_eq(
  $$ select paid, remaining from public.installment_status where id = 'a2000000-0000-0000-0000-000000000001' $$,
  $$ values (0.00::numeric(18, 2), 500.00::numeric(18, 2)) $$,
  'a bounced receipt no longer counts: the installment reopens (rule 27)'
);
select throws_ok(
  $$ update public.customer_receipts set amount = 1 where id = 'a3000000-0000-0000-0000-000000000002' $$,
  'SR003', null, 'a receipt cannot be edited'
);

-- --- Paper status machine ------------------------------------------------------------------------
insert into public.deferred_papers (id, tenant_id, paper_type, number, customer_id, installment_id, amount, due_date) values
  ('a4000000-0000-0000-0000-000000000001', 'aaaaaaaa-0000-0000-0000-0000000000a9', 'PDC', '100200',
   'cd000000-0000-0000-0000-000000000001', 'a2000000-0000-0000-0000-000000000002', 500, current_date + 30),
  ('a4000000-0000-0000-0000-000000000002', 'aaaaaaaa-0000-0000-0000-0000000000a9', 'PROMISSORY_NOTE', 'N-1',
   'cd000000-0000-0000-0000-000000000001', 'a2000000-0000-0000-0000-000000000001', 500, current_date);
select throws_ok(
  $$ update public.deferred_papers set status = 'BOUNCED' where id = 'a4000000-0000-0000-0000-000000000001' $$,
  'SR021', null, 'a cheque cannot bounce before it is deposited or collected'
);
select lives_ok(
  $$ update public.deferred_papers set status = 'DEPOSITED' where id = 'a4000000-0000-0000-0000-000000000001' $$,
  'a held cheque is deposited'
);
select throws_ok(
  $$ update public.deferred_papers set status = 'DEPOSITED' where id = 'a4000000-0000-0000-0000-000000000002' $$,
  'SR021', null, 'a promissory note is never deposited'
);
select throws_ok(
  $$ update public.deferred_papers set amount = 1 where id = 'a4000000-0000-0000-0000-000000000002' $$,
  'SR003', null, 'a paper''s amount never changes'
);

-- --- Notifications are personal ----------------------------------------------------------------------
insert into public.notifications (tenant_id, user_id, kind, dedupe_key) values
  ('aaaaaaaa-0000-0000-0000-0000000000a9', '00000000-0000-0000-0000-0000000ad001', 'INSTALLMENT_DUE_SOON', 'a'),
  ('aaaaaaaa-0000-0000-0000-0000000000a9', '00000000-0000-0000-0000-0000000ad002', 'INSTALLMENT_DUE_SOON', 'a');
set local role authenticated;
select set_config('request.jwt.claims', '{"sub": "00000000-0000-0000-0000-0000000ad001", "role": "authenticated"}', true);
select is((select count(*) from public.notifications), 1::bigint, 'a user sees only their own notifications');

select * from finish();
rollback;
