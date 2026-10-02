-- Partners (SPEC §4.2): ownership must total exactly 100% on every date, the
-- history is append-only, and a partner user sees only their own records.
begin;
set local search_path = public, extensions;
select plan(12);

insert into auth.users (id, email, aud, role, instance_id) values
  ('00000000-0000-0000-0000-0000000ab001', 'p-owner@test.local',   'authenticated', 'authenticated', '00000000-0000-0000-0000-000000000000'),
  ('00000000-0000-0000-0000-0000000ab002', 'p-partner@test.local', 'authenticated', 'authenticated', '00000000-0000-0000-0000-000000000000');

insert into public.tenants (id, name_ar, country_code, currency_code, timezone) values
  ('aaaaaaaa-0000-0000-0000-0000000000a7', 'معرض الشركاء', 'EG', 'EGP', 'Africa/Cairo'),
  ('bbbbbbbb-0000-0000-0000-0000000000b7', 'معرض آخر', 'EG', 'EGP', 'Africa/Cairo');

insert into public.partners (id, tenant_id, name_ar) values
  ('ba000000-0000-0000-0000-000000000001', 'aaaaaaaa-0000-0000-0000-0000000000a7', 'أحمد'),
  ('ba000000-0000-0000-0000-000000000002', 'aaaaaaaa-0000-0000-0000-0000000000a7', 'منى'),
  ('ba000000-0000-0000-0000-000000000003', 'aaaaaaaa-0000-0000-0000-0000000000a7', 'يوسف'),
  ('bb000000-0000-0000-0000-000000000001', 'bbbbbbbb-0000-0000-0000-0000000000b7', 'شريك آخر');

create function pg_temp.check_now() returns void language plpgsql as $$
begin
  set constraints all immediate;
  set constraints all deferred;
end $$;

-- --- 100% rule ------------------------------------------------------------------
insert into public.partner_share_history (tenant_id, partner_id, percentage, effective_from, change_batch_id) values
  ('aaaaaaaa-0000-0000-0000-0000000000a7', 'ba000000-0000-0000-0000-000000000001', 50, '2026-01-01', 'c0000000-0000-0000-0000-0000000000c1'),
  ('aaaaaaaa-0000-0000-0000-0000000000a7', 'ba000000-0000-0000-0000-000000000002', 30, '2026-01-01', 'c0000000-0000-0000-0000-0000000000c1');
select throws_ok($$ select pg_temp.check_now() $$, 'SR010', null, 'shares totalling 80% are rejected at commit');

-- The check stays queued; once the batch is complete it passes.
select lives_ok(
  $$ insert into public.partner_share_history (tenant_id, partner_id, percentage, effective_from, change_batch_id) values
       ('aaaaaaaa-0000-0000-0000-0000000000a7', 'ba000000-0000-0000-0000-000000000003', 20, '2026-01-01', 'c0000000-0000-0000-0000-0000000000c1') $$,
  'adding the third partner completes the batch'
);
select lives_ok($$ select pg_temp.check_now() $$, '50/30/20 totals exactly 100%');

-- A new batch: close the open rows, open new ones (60/40 from July; Youssef leaves).
update public.partner_share_history set effective_to = '2026-06-30'
 where tenant_id = 'aaaaaaaa-0000-0000-0000-0000000000a7' and effective_to is null;
insert into public.partner_share_history (tenant_id, partner_id, percentage, effective_from, change_batch_id) values
  ('aaaaaaaa-0000-0000-0000-0000000000a7', 'ba000000-0000-0000-0000-000000000001', 60, '2026-07-01', 'c0000000-0000-0000-0000-0000000000c2'),
  ('aaaaaaaa-0000-0000-0000-0000000000a7', 'ba000000-0000-0000-0000-000000000002', 40, '2026-07-01', 'c0000000-0000-0000-0000-0000000000c2');
select lives_ok($$ select pg_temp.check_now() $$, 'a new batch from July totals 100%');

select is(
  (select sum(percentage) from public.partner_share_history
    where tenant_id = 'aaaaaaaa-0000-0000-0000-0000000000a7' and effective_from <= '2026-03-15'
      and (effective_to is null or effective_to >= '2026-03-15')),
  100.0000::numeric,
  'history still answers "who owned what" for an earlier date'
);

select throws_ok(
  $$ insert into public.partner_share_history (tenant_id, partner_id, percentage, effective_from, change_batch_id) values
       ('aaaaaaaa-0000-0000-0000-0000000000a7', 'ba000000-0000-0000-0000-000000000001', 10, '2026-08-01', gen_random_uuid()) $$,
  '23P01', null,
  'a partner cannot hold two shares on the same day'
);

-- --- Append-only history -----------------------------------------------------------
select throws_ok(
  $$ update public.partner_share_history set percentage = 55
      where tenant_id = 'aaaaaaaa-0000-0000-0000-0000000000a7' and effective_from = '2026-07-01'
        and partner_id = 'ba000000-0000-0000-0000-000000000001' $$,
  'SR003', null,
  'a recorded share cannot be edited'
);
select throws_ok(
  $$ delete from public.partner_share_history where tenant_id = 'aaaaaaaa-0000-0000-0000-0000000000a7' $$,
  'SR003', null,
  'share history cannot be deleted'
);

-- --- Cross-tenant references ----------------------------------------------------------
select throws_ok(
  $$ insert into public.partner_share_history (tenant_id, partner_id, percentage, effective_from, change_batch_id) values
       ('aaaaaaaa-0000-0000-0000-0000000000a7', 'bb000000-0000-0000-0000-000000000001', 100, '2027-01-01', gen_random_uuid()) $$,
  '23503', null,
  'a share cannot point at another showroom''s partner'
);

-- --- Partner user sees only their own partner record -----------------------------------
insert into public.memberships (tenant_id, user_id, role_id, partner_id) values
  ('aaaaaaaa-0000-0000-0000-0000000000a7', '00000000-0000-0000-0000-0000000ab002',
   (select id from public.roles where code = 'PARTNER' and tenant_id is null), 'ba000000-0000-0000-0000-000000000002');
select throws_ok(
  $$ insert into public.memberships (tenant_id, user_id, role_id, partner_id) values
       ('aaaaaaaa-0000-0000-0000-0000000000a7', '00000000-0000-0000-0000-0000000ab001',
        (select id from public.roles where code = 'OWNER' and tenant_id is null), 'bb000000-0000-0000-0000-000000000001') $$,
  '23503', null,
  'a membership cannot link to another showroom''s partner'
);

set local role authenticated;
select set_config('request.jwt.claims', '{"sub": "00000000-0000-0000-0000-0000000ab002", "role": "authenticated"}', true);
select results_eq(
  $$ select name_ar from public.partners where tenant_id = 'aaaaaaaa-0000-0000-0000-0000000000a7' $$,
  $$ values ('منى'::text) $$,
  'a partner user sees only their own partner record'
);
select is(
  (select count(distinct partner_id) from public.partner_share_history
    where tenant_id = 'aaaaaaaa-0000-0000-0000-0000000000a7'),
  1::bigint,
  'and only their own ownership history'
);

select * from finish();
rollback;
