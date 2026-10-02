-- Structural security guarantees that must hold for every table, now and in
-- later phases (ARCHITECTURE §3–§4). A new table that skips
-- private.secure_table() fails here.
begin;
select plan(12);

select is(
  (select array_agg(c.relname::text order by c.relname)
     from pg_class c
     join pg_namespace n on n.oid = c.relnamespace
    where n.nspname = 'public' and c.relkind in ('r', 'p') and not c.relrowsecurity),
  null,
  'every public table has row level security enabled'
);

select is(
  (select array_agg(c.relname::text order by c.relname)
     from pg_class c
     join pg_namespace n on n.oid = c.relnamespace
     join pg_attribute a on a.attrelid = c.oid and a.attname = 'tenant_id' and not a.attisdropped
    where n.nspname = 'public' and c.relkind in ('r', 'p')
      and not exists (select 1 from pg_policy p where p.polrelid = c.oid)),
  null,
  'every table with tenant_id has at least one RLS policy'
);

select is(
  (select count(*) from information_schema.role_table_grants
    where grantee = 'anon' and table_schema = 'public'),
  0::bigint,
  'anon holds no privileges on public tables'
);

select is(
  (select count(*) from information_schema.role_table_grants
    where grantee = 'service_role' and table_schema = 'public'),
  0::bigint,
  'service_role holds no privileges on public tables (API admin tasks only)'
);

-- Tables the browser may write directly (non-financial CRUD). Empty in Phase 1;
-- every later addition must be added here deliberately.
select is(
  (select array_agg(distinct table_name::text order by table_name::text)
     from information_schema.role_table_grants
    where grantee = 'authenticated' and table_schema = 'public'
      and privilege_type in ('INSERT', 'UPDATE', 'DELETE', 'TRUNCATE')),
  null,
  'the browser cannot write any table yet (allowlist empty in Phase 1)'
);

select is(
  (select array_agg(grantee || ':' || table_name || ':' || privilege_type order by grantee, table_name)
     from information_schema.role_table_grants
    where grantee in ('authenticated', 'app_api') and table_schema = 'public'
      and privilege_type in ('DELETE', 'TRUNCATE')),
  -- Only sale drafts (and their payment legs) are ever deleted, by the API (ERD §1).
  array['app_api:sale_payments:DELETE', 'app_api:sales:DELETE'],
  'no client role may physically delete or truncate, except the API deleting sale drafts'
);

select is(
  (select rolbypassrls from pg_roles where rolname = 'app_api'),
  false,
  'app_api does not bypass RLS'
);

select ok(
  not has_table_privilege('app_api', 'public.audit_log', 'UPDATE')
  and not has_table_privilege('authenticated', 'public.audit_log', 'INSERT'),
  'audit_log is not updatable by the API nor writable by the browser'
);

select is(
  (select count(*) from public.role_permissions rp
     join public.roles r on r.id = rp.role_id
     join public.role_permission_restrictions x
       on x.role_code = r.code and x.permission_code = rp.permission_code),
  0::bigint,
  'no system role bundle contains a restricted permission'
);

select ok(
  not has_function_privilege('authenticated', 'private.effective_permissions(uuid, uuid)', 'EXECUTE'),
  'the browser cannot query another user''s permissions'
);

select is(
  (select array_agg(p.proname::text order by p.proname)
     from pg_proc p join pg_namespace n on n.oid = p.pronamespace
    where n.nspname = 'private' and has_function_privilege('anon', p.oid, 'EXECUTE')),
  null,
  'anon cannot execute any private function'
);

-- Exactly the helpers RLS policies need; adding one must be deliberate.
select is(
  (select array_agg(p.proname::text order by p.proname)
     from pg_proc p join pg_namespace n on n.oid = p.pronamespace
    where n.nspname = 'private' and has_function_privilege('authenticated', p.oid, 'EXECUTE')),
  array[
    'current_actor_id', 'current_tenant_id', 'current_user_id', 'feature_enabled',
    'has_any_permission', 'has_permission', 'is_member', 'is_platform_admin',
    'my_partner_id', 'my_tenant_ids', 'tenant_writable', 'tenants_with_permission'
  ],
  'the browser may execute only the RLS helper allowlist'
);

select * from finish();
rollback;
