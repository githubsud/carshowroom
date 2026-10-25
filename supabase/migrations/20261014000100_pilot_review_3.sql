-- =============================================================================
-- Pilot review 3 (feedback of 2026-10-25, D-134).
-- Customer requests: a car a little above the customer's ceiling is still shown
-- (prices are negotiable), and matching also runs when a car's make, model,
-- year or price change while it is available.
-- =============================================================================

-- How far above the customer's maximum budget a car may be priced and still be
-- suggested (percent, 0 = never above the ceiling).
alter table public.tenant_settings
  add column request_budget_tolerance_pct numeric(5, 2) not null default 10
    check (request_budget_tolerance_pct between 0 and 50);

-- Matching (SPEC §4.6, D-97, D-134): make through the catalogue, model contained,
-- year range, price up to the ceiling plus the showroom's tolerance.
create or replace function private.request_fits(r public.customer_requests, v public.vehicles)
returns boolean
language sql
stable
set search_path = ''
as $$
  select r.status in ('NEW', 'CONTACTED', 'VEHICLE_FOUND', 'NEGOTIATING')
     and (r.make is null or private.make_key(r.make) = private.make_key(v.make))
     and (r.model is null or v.model ilike '%' || btrim(r.model) || '%')
     and (r.year_from is null or coalesce(v.year >= r.year_from, false))
     and (r.year_to is null or coalesce(v.year <= r.year_to, false))
     and (r.budget_max is null or v.asking_price is null
          or v.asking_price <= r.budget_max * (1 + coalesce(
               (select s.request_budget_tolerance_pct from public.tenant_settings s where s.tenant_id = v.tenant_id),
               0) / 100));
$$;

-- Match one request against the cars available now; returns the number of new
-- matches. Suggestions the request no longer fits are dropped unless the
-- customer was already told about the car.
create or replace function private.match_request(p_request uuid)
returns integer
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_count integer;
begin
  delete from public.customer_request_matches m
   using public.customer_requests r, public.vehicles v
   where m.request_id = p_request and r.id = m.request_id and v.id = m.vehicle_id
     and not m.contacted and r.status in ('NEW', 'CONTACTED', 'VEHICLE_FOUND', 'NEGOTIATING')
     and v.status = 'AVAILABLE' and not private.request_fits(r, v);

  insert into public.customer_request_matches (tenant_id, request_id, vehicle_id)
  select r.tenant_id, r.id, v.id
    from public.customer_requests r
    join public.vehicles v on v.tenant_id = r.tenant_id and v.status = 'AVAILABLE'
   where r.id = p_request and private.request_fits(r, v)
  on conflict (request_id, vehicle_id) do nothing;
  get diagnostics v_count = row_count;
  return v_count;
end;
$$;

-- An available car is matched against every open request; members who manage
-- requests are told how many customers asked for it (BACKLOG 6.6).
create or replace function private.vehicle_available_match()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_new integer;
  v_total integer;
begin
  delete from public.customer_request_matches m
   using public.customer_requests r
   where m.vehicle_id = new.id and r.id = m.request_id and not m.contacted
     and r.status in ('NEW', 'CONTACTED', 'VEHICLE_FOUND', 'NEGOTIATING') and not private.request_fits(r, new);

  insert into public.customer_request_matches (tenant_id, request_id, vehicle_id)
  select r.tenant_id, r.id, new.id
    from public.customer_requests r
   where r.tenant_id = new.tenant_id and private.request_fits(r, new)
  on conflict (request_id, vehicle_id) do nothing;
  get diagnostics v_new = row_count;
  if v_new > 0 then
    select count(*) into v_total
      from public.customer_request_matches m join public.customer_requests r on r.id = m.request_id
     where m.vehicle_id = new.id and private.request_fits(r, new);
    insert into public.notifications (tenant_id, user_id, kind, params, entity_type, entity_id, dedupe_key)
    select m.tenant_id, m.user_id, 'REQUEST_MATCH',
           jsonb_build_object('stock_no', new.stock_no, 'vehicle_label', concat_ws(' ', new.make, new.model, new.year),
                              'count', v_total),
           'VEHICLE', new.id, format('match:%s:%s', new.id, txid_current())
      from public.memberships m
     where m.tenant_id = new.tenant_id and m.status = 'ACTIVE'
       and 'request.manage' = any (private.effective_permissions(m.tenant_id, m.user_id))
    on conflict (tenant_id, user_id, dedupe_key) do nothing;
  end if;
  return null;
end;
$$;

drop trigger vehicles_available_match on public.vehicles;
create trigger vehicles_available_match after update of status on public.vehicles
  for each row when (new.status = 'AVAILABLE' and old.status is distinct from 'AVAILABLE')
  execute function private.vehicle_available_match();
-- Details corrected while the car is on sale.
create trigger vehicles_available_rematch after update of make, model, year, asking_price on public.vehicles
  for each row when (new.status = 'AVAILABLE' and old.status = 'AVAILABLE'
                     and (new.make, new.model, new.year, new.asking_price)
                         is distinct from (old.make, old.model, old.year, old.asking_price))
  execute function private.vehicle_available_match();

-- A changed tolerance applies to every open request.
create or replace function private.tenant_settings_rematch()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
declare
  r record;
begin
  for r in
    select id from public.customer_requests
     where tenant_id = new.tenant_id and status in ('NEW', 'CONTACTED', 'VEHICLE_FOUND', 'NEGOTIATING')
  loop
    perform private.match_request(r.id);
  end loop;
  return null;
end;
$$;

create trigger tenant_settings_rematch after update of request_budget_tolerance_pct on public.tenant_settings
  for each row when (new.request_budget_tolerance_pct is distinct from old.request_budget_tolerance_pct)
  execute function private.tenant_settings_rematch();

-- Open requests may now fit cars they missed before (e.g. a car slightly above the ceiling).
do $$
declare
  r record;
begin
  for r in
    select id from public.customer_requests where status in ('NEW', 'CONTACTED', 'VEHICLE_FOUND', 'NEGOTIATING')
  loop
    perform private.match_request(r.id);
  end loop;
end;
$$;

-- -----------------------------------------------------------------------------
-- Grants (every migration ends with the full set).
-- -----------------------------------------------------------------------------
revoke execute on all routines in schema private from public, anon, authenticated, service_role;
grant execute on function
  private.current_tenant_id(), private.current_user_id(), private.current_actor_id(),
  private.my_tenant_ids(), private.tenants_with_permission(text), private.is_member(uuid),
  private.has_permission(uuid, text), private.has_any_permission(uuid, text[]),
  private.my_partner_id(uuid), private.is_platform_admin(), private.tenant_writable(uuid),
  private.feature_enabled(uuid, text)
  to authenticated, app_api;
grant execute on function private.active_tenant_ids(), private.paper_transition_allowed(text, text, text),
  private.match_request(uuid), private.support_granted(uuid), private.create_tenant(uuid, text, text, text),
  private.user_is_platform_admin(uuid), private.platform_tenants(),
  private.platform_update_tenant(uuid, text, text, text, timestamptz), private.user_has_mfa(uuid),
  private.user_owned_tenants(uuid)
  to app_api;
