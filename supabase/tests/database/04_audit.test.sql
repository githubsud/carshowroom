-- Audit log (SPEC §4.15): every change is captured with its actor, and the log
-- is append-only for every role, including the migration owner.
begin;
-- pgTAP lives in the extensions schema; let app_api reach it (rolled back).
set local search_path = public, extensions;
grant usage on schema extensions to app_api;

select plan(9);

insert into auth.users (id, email, aud, role, instance_id) values
  ('00000000-0000-0000-0000-0000000ad001', 'audit-owner@test.local', 'authenticated', 'authenticated', '00000000-0000-0000-0000-000000000000');

insert into public.tenants (id, name_ar, country_code, currency_code, timezone)
values ('aaaaaaaa-0000-0000-0000-0000000000d1', 'معرض التدقيق', 'EG', 'EGP', 'Africa/Cairo');

select is(
  (select count(*) from public.audit_log
    where entity_type = 'tenants' and entity_id = 'aaaaaaaa-0000-0000-0000-0000000000d1' and action = 'INSERT'),
  1::bigint,
  'creating a tenant writes an INSERT audit row'
);

select is(
  (select tenant_id from public.audit_log
    where entity_type = 'tenant_settings' and entity_id = 'aaaaaaaa-0000-0000-0000-0000000000d1'),
  'aaaaaaaa-0000-0000-0000-0000000000d1'::uuid,
  'the auto-created settings row is audited under its tenant'
);

-- A change made through the API carries the acting user and the request id.
set local role app_api;
select set_config('app.tenant_id', 'aaaaaaaa-0000-0000-0000-0000000000d1', true);
select set_config('app.user_id', '00000000-0000-0000-0000-0000000ad001', true);
select set_config('app.request_id', 'req-audit-test', true);
update public.tenant_settings set digit_style = 'ARABIC_INDIC'
 where tenant_id = 'aaaaaaaa-0000-0000-0000-0000000000d1';
reset role;

select results_eq(
  $$ select actor_user_id, actor_kind, request_id, before ->> 'digit_style', after ->> 'digit_style'
       from public.audit_log
      where entity_type = 'tenant_settings' and action = 'UPDATE'
        and tenant_id = 'aaaaaaaa-0000-0000-0000-0000000000d1' $$,
  $$ values ('00000000-0000-0000-0000-0000000ad001'::uuid, 'USER', 'req-audit-test', 'WESTERN', 'ARABIC_INDIC') $$,
  'an API update records actor, request id, before and after'
);

select is(
  (select updated_by from public.tenant_settings where tenant_id = 'aaaaaaaa-0000-0000-0000-0000000000d1'),
  '00000000-0000-0000-0000-0000000ad001'::uuid,
  'updated_by is stamped from the request context'
);

-- created_* cannot be rewritten by an update.
update public.tenant_settings set created_at = '2000-01-01', created_by = '00000000-0000-0000-0000-0000000ad001'
 where tenant_id = 'aaaaaaaa-0000-0000-0000-0000000000d1';
select ok(
  (select created_at > '2020-01-01' and created_by is null
     from public.tenant_settings where tenant_id = 'aaaaaaaa-0000-0000-0000-0000000000d1'),
  'created_at and created_by are immutable'
);

-- A no-op update writes no audit row (now() is fixed inside the transaction,
-- so the stamped updated_at does not change either).
create temporary table audit_count on commit drop as
  select count(*) as n from public.audit_log
   where entity_type = 'tenant_settings' and tenant_id = 'aaaaaaaa-0000-0000-0000-0000000000d1';
update public.tenant_settings set digit_style = digit_style
 where tenant_id = 'aaaaaaaa-0000-0000-0000-0000000000d1';
select is(
  (select count(*) from public.audit_log
    where entity_type = 'tenant_settings' and tenant_id = 'aaaaaaaa-0000-0000-0000-0000000000d1'),
  (select n from audit_count),
  'a no-op update writes no audit row'
);

select throws_ok(
  $$ update public.audit_log set action = 'X' where tenant_id = 'aaaaaaaa-0000-0000-0000-0000000000d1' $$,
  '42501', null,
  'audit rows cannot be updated, even by the owner'
);
select throws_ok(
  $$ delete from public.audit_log where tenant_id = 'aaaaaaaa-0000-0000-0000-0000000000d1' $$,
  '42501', null,
  'audit rows cannot be deleted, even by the owner'
);
select throws_ok(
  $$ truncate public.audit_log $$,
  '42501', null,
  'the audit log cannot be truncated'
);

select * from finish();
rollback;
