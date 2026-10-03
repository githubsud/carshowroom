-- Distribution (rules 22, 23; D-101): a period is distributed once, nothing
-- but closing entries may be dated inside it, and a distribution changes only
-- by being reversed as a whole.
begin;
set local search_path = public, extensions;
select plan(7);

insert into public.tenants (id, name_ar, country_code, currency_code, timezone) values
  ('aaaaaaaa-0000-0000-0000-0000000000ab', 'معرض التوزيع', 'EG', 'EGP', 'Africa/Cairo');
select set_config('app.tenant_id', 'aaaaaaaa-0000-0000-0000-0000000000ab', true);

create temporary table closing on commit drop as
select journal_entry_id from private.post_journal_entry(jsonb_build_object(
  'entry_date', current_date - 5, 'description', 'إقفال', 'source_type', 'PERIOD_CLOSE', 'is_closing', true,
  'lines', jsonb_build_array(
    jsonb_build_object('ledger_account_id',
      (select id from public.ledger_accounts where tenant_id = 'aaaaaaaa-0000-0000-0000-0000000000ab' and system_key = 'OTHER_INCOME'),
      'debit', '100.00'),
    jsonb_build_object('ledger_account_id',
      (select id from public.ledger_accounts where tenant_id = 'aaaaaaaa-0000-0000-0000-0000000000ab' and system_key = 'RETAINED_EARNINGS'),
      'credit', '100.00'))));

insert into public.profit_distributions
  (id, tenant_id, period_from, period_to, profit_policy, prorata_method, rounding_remainder, loss_handling,
   net_profit, distributed, closing_journal_entry_id)
select 'ad100000-0000-0000-0000-000000000001', 'aaaaaaaa-0000-0000-0000-0000000000ab', current_date - 30, current_date - 5,
       'PERIODIC', 'DAY_WEIGHTED', 'LARGEST_REMAINDER', 'ALLOCATE_TO_PARTNERS', 100, 0, journal_entry_id from closing;

select throws_ok(
  $$ insert into public.profit_distributions
       (tenant_id, period_from, period_to, profit_policy, prorata_method, rounding_remainder, loss_handling,
        net_profit, distributed)
     values ('aaaaaaaa-0000-0000-0000-0000000000ab', current_date - 10, current_date - 1, 'PERIODIC', 'DAY_WEIGHTED',
             'LARGEST_REMAINDER', 'ALLOCATE_TO_PARTNERS', 0, 0) $$,
  '23P01', null, 'a period cannot be distributed twice (overlap)'
);
select lives_ok(
  $$ insert into public.profit_distributions
       (tenant_id, period_from, period_to, profit_policy, prorata_method, rounding_remainder, loss_handling,
        net_profit, distributed)
     values ('aaaaaaaa-0000-0000-0000-0000000000ab', current_date - 4, current_date - 4, 'PERIODIC', 'DAY_WEIGHTED',
             'LARGEST_REMAINDER', 'ALLOCATE_TO_PARTNERS', 0, 0) $$,
  'the next period can follow'
);

select throws_ok(
  $$ select private.post_journal_entry(jsonb_build_object(
       'entry_date', current_date - 10, 'description', 'متأخر', 'source_type', 'TEST',
       'lines', jsonb_build_array(
         jsonb_build_object('ledger_account_id',
           (select id from public.ledger_accounts where tenant_id = 'aaaaaaaa-0000-0000-0000-0000000000ab' and system_key = 'EXP_RENT'),
           'debit', '10.00'),
         jsonb_build_object('ledger_account_id',
           (select id from public.ledger_accounts where tenant_id = 'aaaaaaaa-0000-0000-0000-0000000000ab' and system_key = 'OPENING_BALANCE_EQUITY'),
           'credit', '10.00')))) $$,
  'SR030', null, 'nothing but closing entries may be dated inside a distributed period'
);
select lives_ok(
  $$ select private.post_journal_entry(jsonb_build_object(
       'entry_date', current_date - 10, 'description', 'إقفال', 'source_type', 'PROFIT_DISTRIBUTION', 'is_closing', true,
       'lines', jsonb_build_array(
         jsonb_build_object('ledger_account_id',
           (select id from public.ledger_accounts where tenant_id = 'aaaaaaaa-0000-0000-0000-0000000000ab' and system_key = 'RETAINED_EARNINGS'),
           'debit', '1.00'),
         jsonb_build_object('ledger_account_id',
           (select id from public.ledger_accounts where tenant_id = 'aaaaaaaa-0000-0000-0000-0000000000ab' and system_key = 'OPENING_BALANCE_EQUITY'),
           'credit', '1.00')))) $$,
  'closing entries may be dated inside it'
);
select throws_ok(
  $$ update public.profit_distributions set net_profit = 1 where id = 'ad100000-0000-0000-0000-000000000001' $$,
  'SR003', null, 'a distribution cannot be edited'
);
select lives_ok(
  $$ update public.profit_distributions set status = 'REVERSED', reversed_at = now(), reversal_reason = 'خطأ'
      where id = 'ad100000-0000-0000-0000-000000000001' $$,
  'a distribution can be reversed as a whole'
);
select lives_ok(
  $$ select private.post_journal_entry(jsonb_build_object(
       'entry_date', current_date - 10, 'description', 'بعد العكس', 'source_type', 'TEST',
       'lines', jsonb_build_array(
         jsonb_build_object('ledger_account_id',
           (select id from public.ledger_accounts where tenant_id = 'aaaaaaaa-0000-0000-0000-0000000000ab' and system_key = 'EXP_RENT'),
           'debit', '10.00'),
         jsonb_build_object('ledger_account_id',
           (select id from public.ledger_accounts where tenant_id = 'aaaaaaaa-0000-0000-0000-0000000000ab' and system_key = 'OPENING_BALANCE_EQUITY'),
           'credit', '10.00')))) $$,
  'a reversed distribution opens its period again'
);

select * from finish();
rollback;
