-- =============================================================================
-- LOCAL DEVELOPMENT SEED ONLY. Never run against a shared or production
-- database: it sets a known password on app_api and creates demo users.
--
-- Demo users (password for all: Demo-Pass-2026):
--   owner@nour.example        OWNER of معرض النور للسيارات (EG)
--   accountant@nour.example   ACCOUNTANT of معرض النور
--   sales@nour.example        SALES of معرض النور
--   partner@nour.example      PARTNER of معرض النور and PARTNER of Doha Motors (multi-tenant)
--   owner@doha.example        OWNER of Doha Motors (QA) — the "other tenant" for isolation tests
-- =============================================================================

alter role app_api with login password 'app_api_local_dev';

-- Fixed ids keep tests and E2E scripts readable.
-- Tenants
--   11111111-...  معرض النور للسيارات (EG)
--   22222222-...  Doha Motors (QA)
-- Users
--   a0000000-...-0001 owner@nour.example
--   a0000000-...-0002 accountant@nour.example
--   a0000000-...-0003 sales@nour.example
--   a0000000-...-0004 partner@nour.example
--   b0000000-...-0001 owner@doha.example

do $$
declare
  v_users constant jsonb := '[
    {"id": "a0000000-0000-0000-0000-000000000001", "email": "owner@nour.example",      "name": "أحمد المالك"},
    {"id": "a0000000-0000-0000-0000-000000000002", "email": "accountant@nour.example", "name": "منى المحاسبة"},
    {"id": "a0000000-0000-0000-0000-000000000003", "email": "sales@nour.example",      "name": "كريم المبيعات"},
    {"id": "a0000000-0000-0000-0000-000000000004", "email": "partner@nour.example",    "name": "يوسف الشريك"},
    {"id": "b0000000-0000-0000-0000-000000000001", "email": "owner@doha.example",      "name": "Khalid Owner"}
  ]';
  v_user jsonb;
begin
  for v_user in select * from jsonb_array_elements(v_users) loop
    insert into auth.users (
      instance_id, id, aud, role, email, encrypted_password, email_confirmed_at,
      raw_app_meta_data, raw_user_meta_data, created_at, updated_at,
      confirmation_token, recovery_token, email_change, email_change_token_new
    ) values (
      '00000000-0000-0000-0000-000000000000',
      (v_user ->> 'id')::uuid,
      'authenticated', 'authenticated',
      v_user ->> 'email',
      extensions.crypt('Demo-Pass-2026', extensions.gen_salt('bf')),
      now(),
      '{"provider": "email", "providers": ["email"]}',
      jsonb_build_object('full_name', v_user ->> 'name'),
      now(), now(), '', '', '', ''
    );

    insert into auth.identities (
      id, user_id, provider_id, provider, identity_data, last_sign_in_at, created_at, updated_at
    ) values (
      gen_random_uuid(),
      (v_user ->> 'id')::uuid,
      v_user ->> 'id',
      'email',
      jsonb_build_object('sub', v_user ->> 'id', 'email', v_user ->> 'email', 'email_verified', true),
      now(), now(), now()
    );
  end loop;
end
$$;

insert into public.tenants (id, name_ar, name_en, country_code, currency_code, timezone, commercial_reg_no, address, phones)
values
  ('11111111-1111-1111-1111-111111111111', 'معرض النور للسيارات', 'Al Nour Motors', 'EG', 'EGP', 'Africa/Cairo',
   '123456', 'شارع التسعين، القاهرة الجديدة', '{"+201000000001"}'),
  ('22222222-2222-2222-2222-222222222222', 'معرض الدوحة للسيارات', 'Doha Motors', 'QA', 'QAR', 'Asia/Qatar',
   'QA-98765', 'Salwa Road, Doha', '{"+97440000001"}');

insert into public.branches (tenant_id, name_ar, name_en, is_default) values
  ('11111111-1111-1111-1111-111111111111', 'المعرض الرئيسي', 'Main yard', true),
  ('22222222-2222-2222-2222-222222222222', 'الفرع الرئيسي', 'Main branch', true);

insert into public.subscriptions (tenant_id, plan_id, status, trial_ends_at)
select t.id, p.id, 'TRIAL', now() + interval '30 days'
from public.tenants t
cross join public.plans p
where p.code = 'TRIAL';

insert into public.memberships (tenant_id, user_id, role_id)
select m.tenant_id::uuid, m.user_id::uuid, r.id
from (values
  ('11111111-1111-1111-1111-111111111111', 'a0000000-0000-0000-0000-000000000001', 'OWNER'),
  ('11111111-1111-1111-1111-111111111111', 'a0000000-0000-0000-0000-000000000002', 'ACCOUNTANT'),
  ('11111111-1111-1111-1111-111111111111', 'a0000000-0000-0000-0000-000000000003', 'SALES'),
  ('11111111-1111-1111-1111-111111111111', 'a0000000-0000-0000-0000-000000000004', 'PARTNER'),
  ('22222222-2222-2222-2222-222222222222', 'a0000000-0000-0000-0000-000000000004', 'PARTNER'),
  ('22222222-2222-2222-2222-222222222222', 'b0000000-0000-0000-0000-000000000001', 'OWNER')
) as m (tenant_id, user_id, role_code)
join public.roles r on r.code = m.role_code and r.tenant_id is null;
