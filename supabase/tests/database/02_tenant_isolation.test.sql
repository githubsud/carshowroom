-- Cross-tenant isolation (SPEC §3.2, Phase 1 acceptance): a user of tenant A
-- cannot read or write tenant B, neither through the browser role nor through
-- the API role.
begin;
-- pgTAP lives in the extensions schema; let app_api reach it (rolled back).
set local search_path = public, extensions;
grant usage on schema extensions to app_api;

select plan(24);

-- ---------------------------------------------------------------------------
-- Fixtures (as the migration owner; rolled back at the end)
-- ---------------------------------------------------------------------------
insert into auth.users (id, email, aud, role, instance_id) values
  ('00000000-0000-0000-0000-00000000a001', 'iso-a-owner@test.local', 'authenticated', 'authenticated', '00000000-0000-0000-0000-000000000000'),
  ('00000000-0000-0000-0000-00000000a002', 'iso-a-sales@test.local', 'authenticated', 'authenticated', '00000000-0000-0000-0000-000000000000'),
  ('00000000-0000-0000-0000-00000000b001', 'iso-b-owner@test.local', 'authenticated', 'authenticated', '00000000-0000-0000-0000-000000000000'),
  ('00000000-0000-0000-0000-00000000c001', 'iso-multi@test.local',   'authenticated', 'authenticated', '00000000-0000-0000-0000-000000000000'),
  ('00000000-0000-0000-0000-00000000d001', 'iso-none@test.local',    'authenticated', 'authenticated', '00000000-0000-0000-0000-000000000000');

insert into public.tenants (id, name_ar, country_code, currency_code, timezone) values
  ('aaaaaaaa-0000-0000-0000-000000000001', 'معرض أ', 'EG', 'EGP', 'Africa/Cairo'),
  ('bbbbbbbb-0000-0000-0000-000000000001', 'معرض ب', 'QA', 'QAR', 'Asia/Qatar');

insert into public.branches (tenant_id, name_ar) values
  ('aaaaaaaa-0000-0000-0000-000000000001', 'فرع أ'),
  ('bbbbbbbb-0000-0000-0000-000000000001', 'فرع ب');

insert into public.subscriptions (tenant_id, plan_id)
select t, (select id from public.plans where code = 'TRIAL')
from unnest(array['aaaaaaaa-0000-0000-0000-000000000001', 'bbbbbbbb-0000-0000-0000-000000000001']::uuid[]) as t;

insert into public.memberships (tenant_id, user_id, role_id)
select m.t::uuid, m.u::uuid, (select id from public.roles where code = m.r and tenant_id is null)
from (values
  ('aaaaaaaa-0000-0000-0000-000000000001', '00000000-0000-0000-0000-00000000a001', 'OWNER'),
  ('aaaaaaaa-0000-0000-0000-000000000001', '00000000-0000-0000-0000-00000000a002', 'SALES'),
  ('bbbbbbbb-0000-0000-0000-000000000001', '00000000-0000-0000-0000-00000000b001', 'OWNER'),
  ('aaaaaaaa-0000-0000-0000-000000000001', '00000000-0000-0000-0000-00000000c001', 'PARTNER'),
  ('bbbbbbbb-0000-0000-0000-000000000001', '00000000-0000-0000-0000-00000000c001', 'PARTNER')
) as m (t, u, r);

-- Restrict every count below to this test's tenants, so seed data never interferes.
create temporary table iso_tenants on commit drop as
  select unnest(array['aaaaaaaa-0000-0000-0000-000000000001', 'bbbbbbbb-0000-0000-0000-000000000001']::uuid[]) as id;
grant select on iso_tenants to authenticated, app_api;

-- ---------------------------------------------------------------------------
-- Browser role: owner of tenant A
-- ---------------------------------------------------------------------------
set local role authenticated;
select set_config('request.jwt.claims', '{"sub": "00000000-0000-0000-0000-00000000a001", "role": "authenticated"}', true);

select results_eq(
  'select id from public.tenants where id in (select id from iso_tenants)',
  $$ values ('aaaaaaaa-0000-0000-0000-000000000001'::uuid) $$,
  'owner A sees only tenant A'
);
select is((select count(*) from public.tenant_settings where tenant_id in (select id from iso_tenants)), 1::bigint,
  'owner A sees only tenant A settings');
select is((select count(*) from public.branches where tenant_id = 'bbbbbbbb-0000-0000-0000-000000000001'), 0::bigint,
  'owner A sees no branch of tenant B');
select is((select count(*) from public.memberships where tenant_id = 'aaaaaaaa-0000-0000-0000-000000000001'), 3::bigint,
  'owner A (users.manage) sees all memberships of tenant A');
select is((select count(*) from public.memberships where tenant_id = 'bbbbbbbb-0000-0000-0000-000000000001'), 0::bigint,
  'owner A sees no membership of tenant B');
select is((select count(*) from public.subscriptions where tenant_id = 'bbbbbbbb-0000-0000-0000-000000000001'), 0::bigint,
  'owner A sees no subscription of tenant B');
select ok((select count(*) from public.audit_log where tenant_id = 'aaaaaaaa-0000-0000-0000-000000000001') > 0,
  'owner A (audit.view) sees tenant A audit rows');
select is((select count(*) from public.audit_log where tenant_id = 'bbbbbbbb-0000-0000-0000-000000000001'), 0::bigint,
  'owner A sees no audit rows of tenant B');

select throws_ok(
  $$ insert into public.branches (tenant_id, name_ar) values ('aaaaaaaa-0000-0000-0000-000000000001', 'x') $$,
  '42501', null,
  'the browser cannot insert branches, even in its own tenant (API only)'
);
select throws_ok(
  $$ update public.tenants set name_ar = 'x' where id = 'aaaaaaaa-0000-0000-0000-000000000001' $$,
  '42501', null,
  'the browser cannot update the tenant profile (API only)'
);
select throws_ok(
  $$ select * from public.tenant_counters $$,
  '42501', null,
  'the browser cannot read tenant counters'
);

-- Sales of tenant A: no users.manage → only own membership, no audit access.
select set_config('request.jwt.claims', '{"sub": "00000000-0000-0000-0000-00000000a002", "role": "authenticated"}', true);
select is((select count(*) from public.memberships where tenant_id in (select id from iso_tenants)), 1::bigint,
  'sales A sees only own membership');
select is((select count(*) from public.audit_log where tenant_id in (select id from iso_tenants)), 0::bigint,
  'sales A cannot read the audit log');

-- Partner in both tenants sees both; a user with no membership sees nothing.
select set_config('request.jwt.claims', '{"sub": "00000000-0000-0000-0000-00000000c001", "role": "authenticated"}', true);
select is((select count(*) from public.tenants where id in (select id from iso_tenants)), 2::bigint,
  'a user with memberships in A and B sees both tenants');

select set_config('request.jwt.claims', '{"sub": "00000000-0000-0000-0000-00000000d001", "role": "authenticated"}', true);
select is((select count(*) from public.tenants where id in (select id from iso_tenants)), 0::bigint,
  'a user without membership sees no tenant');

-- Owner of tenant B sees nothing of A.
select set_config('request.jwt.claims', '{"sub": "00000000-0000-0000-0000-00000000b001", "role": "authenticated"}', true);
select is((select count(*) from public.branches where tenant_id = 'aaaaaaaa-0000-0000-0000-000000000001'), 0::bigint,
  'owner B sees no branch of tenant A');

-- A disabled membership loses access immediately.
reset role;
update public.memberships set status = 'DISABLED'
 where user_id = '00000000-0000-0000-0000-00000000a002';
set local role authenticated;
select set_config('request.jwt.claims', '{"sub": "00000000-0000-0000-0000-00000000a002", "role": "authenticated"}', true);
select is((select count(*) from public.tenants where id in (select id from iso_tenants)), 0::bigint,
  'a disabled membership sees no tenant');

-- ---------------------------------------------------------------------------
-- API role scoped to tenant A
-- ---------------------------------------------------------------------------
reset role;
set local role app_api;
select set_config('app.tenant_id', 'aaaaaaaa-0000-0000-0000-000000000001', true);
select set_config('app.user_id', '00000000-0000-0000-0000-00000000a001', true);

select is((select count(*) from public.branches where tenant_id in (select id from iso_tenants)), 1::bigint,
  'API scoped to A sees only A branches');
select is((select count(*) from public.tenant_settings where tenant_id = 'bbbbbbbb-0000-0000-0000-000000000001'), 0::bigint,
  'API scoped to A cannot read B settings');

select throws_ok(
  $$ insert into public.branches (tenant_id, name_ar) values ('bbbbbbbb-0000-0000-0000-000000000001', 'x') $$,
  '42501', null,
  'API scoped to A cannot insert a branch for B'
);
select is_empty(
  $$ update public.branches set name_ar = 'x' where tenant_id = 'bbbbbbbb-0000-0000-0000-000000000001' returning id $$,
  'API scoped to A cannot update B branches'
);
select throws_ok(
  $$ insert into public.tenant_counters (tenant_id, counter_key) values ('bbbbbbbb-0000-0000-0000-000000000001', 'x') $$,
  '42501', null,
  'API scoped to A cannot create counters for B'
);
select lives_ok(
  $$ insert into public.branches (tenant_id, name_ar) values ('aaaaaaaa-0000-0000-0000-000000000001', 'فرع جديد') $$,
  'API scoped to A can insert a branch for A'
);

-- Without a tenant context the API sees no tenant data.
select set_config('app.tenant_id', '', true);
select is((select count(*) from public.branches where tenant_id in (select id from iso_tenants)), 0::bigint,
  'API without tenant context sees no branches');

select * from finish();
rollback;
