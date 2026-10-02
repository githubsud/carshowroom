-- Permission resolution (D-10, D-14, approved Q-05 role matrix), tenant
-- overrides, hard restrictions, read-only tenants and feature flags.
begin;
select plan(16);

insert into auth.users (id, email, aud, role, instance_id) values
  ('00000000-0000-0000-0000-0000000aa001', 'perm-owner@test.local',   'authenticated', 'authenticated', '00000000-0000-0000-0000-000000000000'),
  ('00000000-0000-0000-0000-0000000aa002', 'perm-manager@test.local', 'authenticated', 'authenticated', '00000000-0000-0000-0000-000000000000'),
  ('00000000-0000-0000-0000-0000000aa003', 'perm-sales@test.local',   'authenticated', 'authenticated', '00000000-0000-0000-0000-000000000000'),
  ('00000000-0000-0000-0000-0000000aa004', 'perm-acct@test.local',    'authenticated', 'authenticated', '00000000-0000-0000-0000-000000000000'),
  ('00000000-0000-0000-0000-0000000bb002', 'perm-manager-b@test.local','authenticated', 'authenticated', '00000000-0000-0000-0000-000000000000');

insert into public.tenants (id, name_ar, country_code, currency_code, timezone) values
  ('aaaaaaaa-0000-0000-0000-0000000000a1', 'معرض أ', 'EG', 'EGP', 'Africa/Cairo'),
  ('bbbbbbbb-0000-0000-0000-0000000000b1', 'معرض ب', 'QA', 'QAR', 'Asia/Qatar');

insert into public.subscriptions (tenant_id, plan_id)
select t, (select id from public.plans where code = 'TRIAL')
from unnest(array['aaaaaaaa-0000-0000-0000-0000000000a1', 'bbbbbbbb-0000-0000-0000-0000000000b1']::uuid[]) as t;

insert into public.memberships (tenant_id, user_id, role_id)
select m.t::uuid, m.u::uuid, (select id from public.roles where code = m.r and tenant_id is null)
from (values
  ('aaaaaaaa-0000-0000-0000-0000000000a1', '00000000-0000-0000-0000-0000000aa001', 'OWNER'),
  ('aaaaaaaa-0000-0000-0000-0000000000a1', '00000000-0000-0000-0000-0000000aa002', 'MANAGER'),
  ('aaaaaaaa-0000-0000-0000-0000000000a1', '00000000-0000-0000-0000-0000000aa003', 'SALES'),
  ('aaaaaaaa-0000-0000-0000-0000000000a1', '00000000-0000-0000-0000-0000000aa004', 'ACCOUNTANT'),
  ('bbbbbbbb-0000-0000-0000-0000000000b1', '00000000-0000-0000-0000-0000000bb002', 'MANAGER')
) as m (t, u, r);

-- --- Role bundles ----------------------------------------------------------
select is(
  cardinality(private.effective_permissions('aaaaaaaa-0000-0000-0000-0000000000a1', '00000000-0000-0000-0000-0000000aa001')),
  (select count(*)::int from public.permissions where scope = 'TENANT'),
  'owner holds every tenant permission'
);
select ok(
  not ('vehicle.view_cost' = any (private.effective_permissions('aaaaaaaa-0000-0000-0000-0000000000a1', '00000000-0000-0000-0000-0000000aa003'))),
  'sales does not hold vehicle.view_cost'
);
select ok(
  not (private.effective_permissions('aaaaaaaa-0000-0000-0000-0000000000a1', '00000000-0000-0000-0000-0000000aa002')
       && array['vehicle.view_min_price', 'sale.post', 'tenant.settings.manage', 'period.unlock', 'partner.equity.change']),
  'manager default: no min price, no sale posting, no settings, no unlock, no equity change (Q-05)'
);
select ok(
  not (private.effective_permissions('aaaaaaaa-0000-0000-0000-0000000000a1', '00000000-0000-0000-0000-0000000aa004')
       && array['tenant.settings.manage', 'period.lock', 'period.unlock', 'profit.distribute', 'users.manage']),
  'accountant: no settings, no period lock/unlock, no distribution, no user management (Q-05)'
);
select is(
  private.effective_permissions('aaaaaaaa-0000-0000-0000-0000000000a1', '00000000-0000-0000-0000-0000000bb002'),
  '{}'::text[],
  'a user has no permissions in a tenant where they are not a member'
);

-- --- Tenant overrides ---------------------------------------------------------
insert into public.tenant_role_permission_overrides (tenant_id, role_id, permission_code, granted)
values ('aaaaaaaa-0000-0000-0000-0000000000a1', (select id from public.roles where code = 'MANAGER' and tenant_id is null), 'sale.post', true);

select ok(
  'sale.post' = any (private.effective_permissions('aaaaaaaa-0000-0000-0000-0000000000a1', '00000000-0000-0000-0000-0000000aa002')),
  'a tenant override lets the manager of tenant A post sales'
);
select ok(
  not ('sale.post' = any (private.effective_permissions('bbbbbbbb-0000-0000-0000-0000000000b1', '00000000-0000-0000-0000-0000000bb002'))),
  'the override does not leak to the manager of tenant B'
);

insert into public.tenant_role_permission_overrides (tenant_id, role_id, permission_code, granted)
values ('aaaaaaaa-0000-0000-0000-0000000000a1', (select id from public.roles where code = 'ACCOUNTANT' and tenant_id is null), 'cash.transact', false);

select ok(
  not ('cash.transact' = any (private.effective_permissions('aaaaaaaa-0000-0000-0000-0000000000a1', '00000000-0000-0000-0000-0000000aa004'))),
  'a revoking override removes a permission from the bundle'
);

select throws_ok(
  $$ insert into public.tenant_role_permission_overrides (tenant_id, role_id, permission_code, granted)
     values ('aaaaaaaa-0000-0000-0000-0000000000a1', (select id from public.roles where code = 'SALES' and tenant_id is null), 'vehicle.view_cost', true) $$,
  '23514', null,
  'no override can give sales vehicle.view_cost'
);
select throws_ok(
  $$ insert into public.tenant_role_permission_overrides (tenant_id, role_id, permission_code, granted)
     values ('aaaaaaaa-0000-0000-0000-0000000000a1', (select id from public.roles where code = 'OWNER' and tenant_id is null), 'platform.tenants.manage', true) $$,
  '23514', null,
  'platform permissions cannot be granted to tenant roles'
);

-- --- Composite tenant safety for roles ---------------------------------------
insert into public.roles (id, tenant_id, code, name_ar, name_en)
values ('cccccccc-0000-0000-0000-0000000000c1', 'bbbbbbbb-0000-0000-0000-0000000000b1', 'CUSTOM', 'مخصص', 'Custom');

select throws_ok(
  $$ update public.memberships set role_id = 'cccccccc-0000-0000-0000-0000000000c1'
      where user_id = '00000000-0000-0000-0000-0000000aa003' $$,
  '23514', null,
  'a membership cannot use a role belonging to another tenant'
);

-- --- Browser helpers ------------------------------------------------------------
set local role authenticated;
select set_config('request.jwt.claims', '{"sub": "00000000-0000-0000-0000-0000000aa003", "role": "authenticated"}', true);
select ok(
  private.has_permission('aaaaaaaa-0000-0000-0000-0000000000a1', 'vehicle.view')
  and not private.has_permission('aaaaaaaa-0000-0000-0000-0000000000a1', 'vehicle.view_cost'),
  'has_permission resolves the signed-in sales user correctly'
);
reset role;

-- --- Read-only tenants and feature flags -------------------------------------
select ok(private.tenant_writable('aaaaaaaa-0000-0000-0000-0000000000a1'), 'a trial tenant is writable');
update public.subscriptions set status = 'SUSPENDED' where tenant_id = 'aaaaaaaa-0000-0000-0000-0000000000a1';
select ok(not private.tenant_writable('aaaaaaaa-0000-0000-0000-0000000000a1'), 'a suspended tenant is read-only');

select ok(private.feature_enabled('aaaaaaaa-0000-0000-0000-0000000000a1', 'installments'), 'plan default enables installments');
insert into public.feature_flags (tenant_id, flag_key, enabled)
values ('aaaaaaaa-0000-0000-0000-0000000000a1', 'installments', false);
select ok(not private.feature_enabled('aaaaaaaa-0000-0000-0000-0000000000a1', 'installments'), 'a tenant override disables a plan feature');

select * from finish();
rollback;
