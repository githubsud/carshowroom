-- =============================================================================
-- User administration helpers for the API (BACKLOG 1.9). auth.users is not
-- readable by app_api; these SECURITY DEFINER functions expose only what user
-- management needs, scoped to the tenant in the request context.
-- =============================================================================

-- Members of the current tenant with their login email and display name.
create or replace function private.tenant_members()
returns table (
  membership_id   uuid,
  user_id         uuid,
  email           text,
  full_name       text,
  role_code       text,
  status          text,
  partner_id      uuid,
  last_sign_in_at timestamptz,
  created_at      timestamptz
)
language sql
stable
security definer
set search_path = ''
as $$
  select m.id, m.user_id, u.email::text, u.raw_user_meta_data ->> 'full_name',
         r.code, m.status, m.partner_id, u.last_sign_in_at, m.created_at
    from public.memberships m
    join public.roles r on r.id = m.role_id
    join auth.users u on u.id = m.user_id
   where m.tenant_id = private.current_tenant_id()
   order by r.sort_order, u.email;
$$;

-- Existing account for an email, so inviting a partner who already uses the
-- product in another showroom adds a membership instead of a second account.
create or replace function private.find_user_id_by_email(p_email text)
returns uuid
language sql
stable
security definer
set search_path = ''
as $$
  select u.id from auth.users u where lower(u.email) = lower(btrim(p_email)) limit 1;
$$;

revoke execute on function private.tenant_members(), private.find_user_id_by_email(text)
  from public, anon, authenticated, service_role;
grant execute on function private.tenant_members() to app_api;
grant execute on function private.find_user_id_by_email(text) to app_api;
