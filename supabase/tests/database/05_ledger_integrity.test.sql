-- Ledger integrity enforced by the database (SPEC §5, Phase 2 acceptance):
-- unbalanced, locked-period and cross-tenant postings fail at DB level even
-- when every application check is bypassed.
begin;
set local search_path = public, extensions;
grant usage on schema extensions to app_api;

select plan(34);

-- ---------------------------------------------------------------------------
-- Fixtures: tenants A and B (chart of accounts is seeded automatically),
-- tenant A gets a cash box (1101) and a bank account (1201).
-- ---------------------------------------------------------------------------
insert into public.tenants (id, name_ar, country_code, currency_code, timezone) values
  ('aaaaaaaa-0000-0000-0000-00000000aaaa', 'معرض أ', 'EG', 'EGP', 'Africa/Cairo'),
  ('bbbbbbbb-0000-0000-0000-00000000bbbb', 'معرض ب', 'QA', 'QAR', 'Asia/Qatar');

insert into public.ledger_accounts (id, tenant_id, code, parent_id, name_ar, name_en, type, normal_side, is_postable, subledger)
select v.id::uuid, 'aaaaaaaa-0000-0000-0000-00000000aaaa', v.code,
       (select id from public.ledger_accounts where tenant_id = 'aaaaaaaa-0000-0000-0000-00000000aaaa' and code = v.parent),
       v.name, v.name, 'ASSET', 'DEBIT', true, 'CASH_ACCOUNT'
from (values
  ('a1101000-0000-0000-0000-000000000000', '1101', '1100', 'Main cash box'),
  ('a1201000-0000-0000-0000-000000000000', '1201', '1200', 'CIB')
) as v (id, code, parent, name);

insert into public.cash_accounts (id, tenant_id, kind, name_ar, ledger_account_id, is_default) values
  ('ca5b0000-0000-0000-0000-000000000001', 'aaaaaaaa-0000-0000-0000-00000000aaaa', 'CASH_BOX', 'الخزنة الرئيسية', 'a1101000-0000-0000-0000-000000000000', true),
  ('ba4c0000-0000-0000-0000-000000000001', 'aaaaaaaa-0000-0000-0000-00000000aaaa', 'BANK', 'CIB', 'a1201000-0000-0000-0000-000000000000', false);

-- Entry builder: rule 20 general expense (Dr rent / Cr cash box).
create function pg_temp.expense(p_debit text, p_credit text, p_date date default '2026-10-02')
returns jsonb language sql as $$
  select jsonb_build_object(
    'entry_date', p_date,
    'description', 'إيجار',
    'source_type', 'GENERAL_EXPENSE',
    'lines', jsonb_build_array(
      jsonb_build_object('ledger_account_id',
        (select id from public.ledger_accounts where tenant_id = 'aaaaaaaa-0000-0000-0000-00000000aaaa' and system_key = 'EXP_RENT'),
        'debit', p_debit),
      jsonb_build_object('ledger_account_id', 'a1101000-0000-0000-0000-000000000000',
        'credit', p_credit, 'cash_account_id', 'ca5b0000-0000-0000-0000-000000000001')))
$$;

-- Post, then force the deferred balance check to run now (it normally runs at commit).
create function pg_temp.post_now(p_entry jsonb)
returns bigint language plpgsql as $$
declare v_no bigint;
begin
  select entry_no into v_no from private.post_journal_entry(p_entry);
  set constraints all immediate;
  set constraints all deferred;
  return v_no;
end $$;

grant execute on all functions in schema pg_temp to app_api;

-- ---------------------------------------------------------------------------
-- Chart of accounts seeding
-- ---------------------------------------------------------------------------
select is(
  (select count(*) from public.ledger_accounts where tenant_id = 'bbbbbbbb-0000-0000-0000-00000000bbbb'),
  (select count(*) from public.coa_template),
  'a new tenant gets the full chart of accounts'
);
select is(
  (select count(*) from public.ledger_accounts a
     join public.ledger_accounts p on p.id = a.parent_id
    where a.tenant_id = 'bbbbbbbb-0000-0000-0000-00000000bbbb'),
  (select count(*) from public.coa_template where parent_code is not null),
  'every seeded child account is linked to its parent'
);
select is(
  (select count(*) from public.expense_categories where tenant_id = 'bbbbbbbb-0000-0000-0000-00000000bbbb'),
  17::bigint,
  'seeded expense categories: 7 general + 10 vehicle'
);
select is(
  (select count(*) from public.payment_methods where tenant_id = 'bbbbbbbb-0000-0000-0000-00000000bbbb'),
  5::bigint,
  'seeded payment methods'
);
select throws_ok(
  $$ update public.ledger_accounts set code = '9999'
      where tenant_id = 'bbbbbbbb-0000-0000-0000-00000000bbbb' and code = '4100' $$,
  'SR003', null,
  'an account code cannot change once created'
);

-- ---------------------------------------------------------------------------
-- Posting as the API role, tenant A
-- ---------------------------------------------------------------------------
-- Captured now: once scoped to tenant A, RLS hides tenant B's accounts.
select set_config('test.b_rent',
  (select id::text from public.ledger_accounts where tenant_id = 'bbbbbbbb-0000-0000-0000-00000000bbbb' and system_key = 'EXP_RENT'),
  true);

set local role app_api;
select set_config('app.tenant_id', 'aaaaaaaa-0000-0000-0000-00000000aaaa', true);
select set_config('app.user_id', '00000000-0000-0000-0000-000000000001', true);

select is(pg_temp.post_now(pg_temp.expense('25000.00', '25000.00')), 1::bigint, 'first entry gets number 1');
select is(pg_temp.post_now(pg_temp.expense('100.50', '100.50')), 2::bigint, 'entry numbers are sequential');
select is(
  (select status from public.accounting_periods
    where tenant_id = 'aaaaaaaa-0000-0000-0000-00000000aaaa' and month = '2026-10-01'),
  'OPEN',
  'the period is created OPEN on first posting'
);
select is(
  (select array_agg(l.entry_date) from public.journal_lines l
     join public.journal_entries e on e.id = l.journal_entry_id where e.entry_no = 1
      and e.tenant_id = 'aaaaaaaa-0000-0000-0000-00000000aaaa'),
  array['2026-10-02', '2026-10-02']::date[],
  'lines carry the entry date'
);

-- --- Balance ---------------------------------------------------------------
select throws_ok(
  $$ select pg_temp.post_now(pg_temp.expense('100.00', '90.00')) $$,
  'SR002', null,
  'an unbalanced entry is rejected by the database'
);
select throws_ok(
  $$ select private.post_journal_entry(jsonb_build_object(
       'entry_date', '2026-10-02', 'description', 'x', 'source_type', 'TEST',
       'lines', jsonb_build_array(jsonb_build_object(
         'ledger_account_id', 'a1101000-0000-0000-0000-000000000000', 'debit', '10.00',
         'cash_account_id', 'ca5b0000-0000-0000-0000-000000000001')))) $$,
  'SR002', null,
  'a single-line entry is rejected'
);
select throws_ok(
  $$ select pg_temp.post_now(pg_temp.expense('10.005', '10.005')) $$,
  'SR007', null,
  'amounts with more than 2 decimals are rejected, never rounded'
);
select throws_ok(
  $$ select pg_temp.post_now(pg_temp.expense('-5.00', '-5.00')) $$,
  '23514', null,
  'negative amounts violate the one-side check'
);
select throws_ok(
  $$ select pg_temp.post_now(jsonb_set(pg_temp.expense('10.00', '10.00'), '{lines,0,credit}', '"10.00"')) $$,
  '23514', null,
  'a line with both debit and credit is rejected'
);

-- --- Accounts and subledgers --------------------------------------------------
select throws_ok(
  $$ select pg_temp.post_now(jsonb_set(pg_temp.expense('10.00', '10.00'), '{lines,0,ledger_account_id}',
       to_jsonb((select id from public.ledger_accounts where tenant_id = 'aaaaaaaa-0000-0000-0000-00000000aaaa' and code = '6000')))) $$,
  'SR005', null,
  'header accounts are not postable'
);
select throws_ok(
  $$ select pg_temp.post_now(jsonb_set(pg_temp.expense('10.00', '10.00'), '{lines,1,cash_account_id}', 'null')) $$,
  'SR006', null,
  'a cash ledger line needs its cash account'
);
select throws_ok(
  $$ select pg_temp.post_now(jsonb_set(pg_temp.expense('10.00', '10.00'), '{lines,1,cash_account_id}',
       '"ba4c0000-0000-0000-0000-000000000001"')) $$,
  'SR006', null,
  'a cash account id must match its own ledger account'
);
select throws_ok(
  $$ select pg_temp.post_now(jsonb_set(pg_temp.expense('10.00', '10.00'), '{lines,0,ledger_account_id}',
       to_jsonb((select id from public.ledger_accounts where tenant_id = 'aaaaaaaa-0000-0000-0000-00000000aaaa' and code = '3100')))) $$,
  'SR006', null,
  'a partner account needs a partner id'
);

-- --- Cross-tenant ---------------------------------------------------------------
select throws_ok(
  $$ select pg_temp.post_now(jsonb_set(pg_temp.expense('10.00', '10.00'), '{lines,0,ledger_account_id}',
       to_jsonb(current_setting('test.b_rent')))) $$,
  '23503', null,
  'posting to another tenant''s account fails at the database'
);

-- --- Immutability and direct writes -----------------------------------------------
select throws_ok(
  $$ insert into public.journal_entries (tenant_id, entry_no, entry_date, description, source_type, period_id)
     values ('aaaaaaaa-0000-0000-0000-00000000aaaa', 99, '2026-10-02', 'x', 'TEST', gen_random_uuid()) $$,
  '42501', null,
  'the API role cannot insert journal entries directly'
);
select throws_ok(
  $$ update public.journal_lines set debit = 1 where tenant_id = 'aaaaaaaa-0000-0000-0000-00000000aaaa' $$,
  '42501', null,
  'the API role cannot update journal lines'
);

-- --- Reversal (rule 24) --------------------------------------------------------------
select is(
  (select entry_no from private.reverse_journal_entry(
     (select id from public.journal_entries where tenant_id = 'aaaaaaaa-0000-0000-0000-00000000aaaa' and entry_no = 1),
     'خطأ في الحساب', '2026-10-03')),
  3::bigint,
  'a reversal is a new, numbered entry'
);
select is(
  (select sum(debit - credit) from public.journal_lines l join public.journal_entries e on e.id = l.journal_entry_id
    where e.tenant_id = 'aaaaaaaa-0000-0000-0000-00000000aaaa' and e.entry_no in (1, 3)),
  0::numeric,
  'the reversal mirrors the original exactly'
);
select is(
  (select r.entry_no from public.journal_entries o join public.journal_entries r on r.id = o.reversed_by_id
    where o.tenant_id = 'aaaaaaaa-0000-0000-0000-00000000aaaa' and o.entry_no = 1),
  3::bigint,
  'the original is linked to its reversal'
);
select throws_ok(
  $$ select * from private.reverse_journal_entry(
       (select id from public.journal_entries where tenant_id = 'aaaaaaaa-0000-0000-0000-00000000aaaa' and entry_no = 1),
       'again', '2026-10-03') $$,
  'SR004', null,
  'an entry cannot be reversed twice'
);
select throws_ok(
  $$ select * from private.reverse_journal_entry(
       (select id from public.journal_entries where tenant_id = 'aaaaaaaa-0000-0000-0000-00000000aaaa' and entry_no = 3),
       'undo', '2026-10-03') $$,
  'SR008', null,
  'a reversal cannot itself be reversed'
);
select throws_ok(
  $$ select * from private.reverse_journal_entry(
       (select id from public.journal_entries where tenant_id = 'aaaaaaaa-0000-0000-0000-00000000aaaa' and entry_no = 2),
       '   ', '2026-10-03') $$,
  'SR007', null,
  'a reversal needs a reason'
);

-- --- Locked periods -------------------------------------------------------------------
update public.accounting_periods set status = 'LOCKED', locked_at = now()
 where tenant_id = 'aaaaaaaa-0000-0000-0000-00000000aaaa' and month = '2026-10-01';

select throws_ok(
  $$ select pg_temp.post_now(pg_temp.expense('10.00', '10.00', '2026-10-15')) $$,
  'SR001', null,
  'posting into a locked month fails'
);
select throws_ok(
  $$ select * from private.reverse_journal_entry(
       (select id from public.journal_entries where tenant_id = 'aaaaaaaa-0000-0000-0000-00000000aaaa' and entry_no = 2),
       'fix', '2026-10-20') $$,
  'SR001', null,
  'a reversal dated in a locked month fails'
);
select lives_ok(
  $$ select * from private.reverse_journal_entry(
       (select id from public.journal_entries where tenant_id = 'aaaaaaaa-0000-0000-0000-00000000aaaa' and entry_no = 2),
       'fix', '2026-11-01') $$,
  'an entry in a locked month can be reversed in an open month'
);

-- --- Tenant context ---------------------------------------------------------------------
select set_config('app.tenant_id', 'bbbbbbbb-0000-0000-0000-00000000bbbb', true);
select throws_ok(
  $$ select * from private.reverse_journal_entry(
       (select id from public.journal_entries where tenant_id = 'aaaaaaaa-0000-0000-0000-00000000aaaa' and entry_no = 2),
       'x', '2026-11-01') $$,
  'SR007', null,
  'tenant B cannot reverse tenant A''s entries'
);
select is(
  (select count(*) from public.journal_entries where tenant_id = 'aaaaaaaa-0000-0000-0000-00000000aaaa'),
  0::bigint,
  'tenant B cannot see tenant A''s entries'
);
select set_config('app.tenant_id', '', true);
select throws_ok(
  $$ select pg_temp.post_now(pg_temp.expense('10.00', '10.00', '2026-11-02')) $$,
  'SR007', null,
  'posting without a tenant context fails'
);

-- --- Owner bypass: even the migration owner cannot break the rules -----------------------
reset role;
select throws_ok(
  $$ delete from public.journal_lines where tenant_id = 'aaaaaaaa-0000-0000-0000-00000000aaaa' $$,
  'SR003', null,
  'posted lines cannot be deleted, even by the owner'
);

select * from finish();
rollback;
