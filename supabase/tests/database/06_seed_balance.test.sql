-- Balance check on the seed data (SPEC §15, DECISIONS C-07): for every tenant
-- the ledger balances and assets = liabilities + equity + (income - expenses).
-- Runs in CI after `supabase start`, which loads supabase/seed.sql.
begin;
select plan(4);

select is(
  (select count(*) from (
     select tenant_id from public.journal_lines group by tenant_id having sum(debit) <> sum(credit)) x),
  0::bigint,
  'every tenant''s ledger balances (total debit = total credit)'
);

select is(
  (select count(*) from (
     select l.tenant_id,
            sum(case when a.type = 'ASSET' then l.debit - l.credit else 0 end) as assets,
            sum(case when a.type <> 'ASSET' then l.credit - l.debit else 0 end) as claims
       from public.journal_lines l join public.ledger_accounts a on a.id = l.ledger_account_id
      group by l.tenant_id) x
    where assets <> claims),
  0::bigint,
  'assets = liabilities + equity + current result, for every tenant'
);

select is(
  (select count(*) from public.journal_entries e
    where (select count(*) from public.journal_lines l where l.journal_entry_id = e.id) < 2),
  0::bigint,
  'no entry has fewer than two lines'
);

select ok(
  (select count(*) from public.journal_entries) > 0,
  'the seed contains ledger activity to check'
);

select * from finish();
rollback;
