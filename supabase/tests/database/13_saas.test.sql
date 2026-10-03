-- SaaS layer (SPEC §4.16): a suspended showroom is read-only in the database,
-- support access exists only inside a live grant, signup gives a trial owner.
begin;
set local search_path = public, extensions;
select plan(7);

insert into auth.users (id, email, aud, role, instance_id) values
  ('00000000-0000-0000-0000-0000000af001', 's-owner@test.local', 'authenticated', 'authenticated', '00000000-0000-0000-0000-000000000000');

select lives_ok(
  $$ select private.create_tenant('00000000-0000-0000-0000-0000000af001', 'معرض جديد', null, 'EG') $$,
  'signup creates a showroom'
);
create temporary table created on commit drop as
  select m.tenant_id from public.memberships m where m.user_id = '00000000-0000-0000-0000-0000000af001';
select is(
  (select s.status from public.subscriptions s join created c on c.tenant_id = s.tenant_id),
  'TRIAL', 'on the trial plan'
);

select lives_ok(
  $$ insert into public.customers (tenant_id, name) select tenant_id, 'عميل' from created $$,
  'an active showroom can be written'
);
update public.subscriptions set status = 'SUSPENDED' where tenant_id = (select tenant_id from created);
select throws_ok(
  $$ insert into public.customers (tenant_id, name) select tenant_id, 'عميل ٢' from created $$,
  'SR040', null, 'a suspended showroom is read-only'
);
select throws_ok(
  $$ update public.customers set name = 'x' where tenant_id = (select tenant_id from created) $$,
  'SR040', null, 'existing data cannot be changed either'
);

select is(private.support_granted((select tenant_id from created)), false, 'no grant, no support access');
insert into public.support_grants (tenant_id, granted_by, reason, expires_at)
select tenant_id, '00000000-0000-0000-0000-0000000af001', 'مساعدة', now() + interval '1 hour' from created;
select is(private.support_granted((select tenant_id from created)), true, 'a live grant opens support access');

select * from finish();
rollback;
