-- =============================================================================
-- Pilot accountant review, first changes (DECISIONS answer log 2026-10-03).
-- * Q-42: request matching treats Arabic and English make names as the same
--   (هيونداي = Hyundai) through a make alias catalogue.
-- * Q-41: cancelling the sale of a consigned car needs its own permission,
--   held by the owner and the manager.
-- * P-12 revised: a sales discount is its own line, on account 4150.
-- * D-71 follow-up: one direct expense can be split over several cars.
-- =============================================================================

-- -----------------------------------------------------------------------------
-- Make aliases (Q-42). Private reference data, used only by the matching
-- functions, which run as their owner.
-- -----------------------------------------------------------------------------

-- Folds the spellings people type for the same make: case, spaces, hyphens,
-- dots, tatweel, and the Arabic letters written several ways (أ إ آ ا, ى ي, ة ه).
create or replace function private.make_norm(p_make text)
returns text
language sql
immutable
set search_path = ''
as $$
  select nullif(
    regexp_replace(translate(lower(btrim(p_make)), 'أإآىة', 'ااايه'), '[[:space:]._ـ-]+', '', 'g'),
    ''
  );
$$;

create table private.make_aliases (
  alias_key text primary key,
  make      text not null
);

insert into private.make_aliases (alias_key, make)
select private.make_norm(a.alias), a.make
from (values
  ('Toyota', 'toyota'), ('تويوتا', 'toyota'),
  ('Hyundai', 'hyundai'), ('هيونداي', 'hyundai'), ('هيونداى', 'hyundai'), ('هونداي', 'hyundai'),
  ('Kia', 'kia'), ('كيا', 'kia'),
  ('Nissan', 'nissan'), ('نيسان', 'nissan'),
  ('Chevrolet', 'chevrolet'), ('Chevy', 'chevrolet'), ('شيفروليه', 'chevrolet'), ('شفروليه', 'chevrolet'),
  ('شيفرولية', 'chevrolet'), ('شيفورليه', 'chevrolet'),
  ('Mitsubishi', 'mitsubishi'), ('ميتسوبيشي', 'mitsubishi'), ('متسوبيشي', 'mitsubishi'), ('ميتسوبيشى', 'mitsubishi'),
  ('Suzuki', 'suzuki'), ('سوزوكي', 'suzuki'), ('سوزوكى', 'suzuki'),
  ('Renault', 'renault'), ('رينو', 'renault'),
  ('Peugeot', 'peugeot'), ('بيجو', 'peugeot'), ('بيجوه', 'peugeot'),
  ('Fiat', 'fiat'), ('فيات', 'fiat'),
  ('Skoda', 'skoda'), ('سكودا', 'skoda'),
  ('Volkswagen', 'volkswagen'), ('VW', 'volkswagen'), ('فولكس', 'volkswagen'), ('فولكس فاجن', 'volkswagen'),
  ('فولكسفاجن', 'volkswagen'),
  ('Mercedes', 'mercedes'), ('Mercedes-Benz', 'mercedes'), ('Benz', 'mercedes'), ('مرسيدس', 'mercedes'),
  ('مرسيدس بنز', 'mercedes'), ('بنز', 'mercedes'),
  ('BMW', 'bmw'), ('بي ام دبليو', 'bmw'), ('بي إم دبليو', 'bmw'), ('بى ام دبليو', 'bmw'), ('بيم', 'bmw'),
  ('Audi', 'audi'), ('أودي', 'audi'), ('اودى', 'audi'),
  ('Opel', 'opel'), ('أوبل', 'opel'),
  ('Chery', 'chery'), ('شيري', 'chery'), ('شيرى', 'chery'),
  ('MG', 'mg'), ('ام جي', 'mg'), ('إم جي', 'mg'), ('ام جى', 'mg'),
  ('Geely', 'geely'), ('جيلي', 'geely'), ('جيلى', 'geely'),
  ('BYD', 'byd'), ('بي واي دي', 'byd'),
  ('Haval', 'haval'), ('هافال', 'haval'),
  ('Jetour', 'jetour'), ('جيتور', 'jetour'),
  ('Jeep', 'jeep'), ('جيب', 'jeep'),
  ('Ford', 'ford'), ('فورد', 'ford'),
  ('Honda', 'honda'), ('هوندا', 'honda'),
  ('Mazda', 'mazda'), ('مازدا', 'mazda'),
  ('Lada', 'lada'), ('لادا', 'lada'),
  ('Daewoo', 'daewoo'), ('دايو', 'daewoo'), ('دايوو', 'daewoo'),
  ('Citroen', 'citroen'), ('Citroën', 'citroen'), ('ستروين', 'citroen'), ('سيتروين', 'citroen'),
  ('Seat', 'seat'), ('سيات', 'seat'),
  ('Subaru', 'subaru'), ('سوبارو', 'subaru'),
  ('Lexus', 'lexus'), ('لكزس', 'lexus'), ('ليكزس', 'lexus'),
  ('Land Rover', 'land rover'), ('لاند روفر', 'land rover'),
  ('Range Rover', 'range rover'), ('رنج روفر', 'range rover'), ('رينج روفر', 'range rover'),
  ('Proton', 'proton'), ('بروتون', 'proton'),
  ('Brilliance', 'brilliance'), ('بريليانس', 'brilliance'),
  ('Speranza', 'speranza'), ('سبيرانزا', 'speranza'),
  ('Dodge', 'dodge'), ('دودج', 'dodge'),
  ('GMC', 'gmc'), ('جي ام سي', 'gmc'),
  ('Infiniti', 'infiniti'), ('انفينيتي', 'infiniti'),
  ('Porsche', 'porsche'), ('بورش', 'porsche'),
  ('Isuzu', 'isuzu'), ('ايسوزو', 'isuzu')
) as a (alias, make)
on conflict (alias_key) do nothing;

-- The make a name stands for: the catalogue entry, or the folded spelling itself
-- for makes not in the catalogue (they still match when spelled the same).
create or replace function private.make_key(p_make text)
returns text
language sql
stable
set search_path = ''
as $$
  select coalesce(
    (select a.make from private.make_aliases a where a.alias_key = private.make_norm(p_make)),
    private.make_norm(p_make)
  );
$$;

-- Matching (SPEC §4.6, D-97) now compares makes through the catalogue.
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
     and (r.budget_max is null or v.asking_price is null or v.asking_price <= r.budget_max);
$$;

-- Open requests may now fit cars they missed before.
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
-- Cancelling a consigned car's sale (Q-41): owner and manager only.
-- -----------------------------------------------------------------------------
insert into public.permissions (code, scope, description)
values ('sale.cancel_consigned', 'TENANT', 'Cancel the posted sale of a consigned car');

insert into public.role_permissions (role_id, permission_code)
select r.id, 'sale.cancel_consigned'
from public.roles r
where r.tenant_id is null and r.code in ('OWNER', 'MANAGER');

-- -----------------------------------------------------------------------------
-- Sales discounts (P-12 revised): a contra-income account, so the discount on
-- each sold car stays visible and reviewable in the ledger and the P&L.
-- -----------------------------------------------------------------------------
insert into public.coa_template (code, parent_code, name_ar, name_en, type, normal_side, is_postable, subledger, system_key)
values ('4150', '4000', 'خصومات المبيعات', 'Sales discounts', 'INCOME', 'DEBIT', true, 'VEHICLE', 'SALES_DISCOUNTS')
on conflict do nothing;

insert into public.ledger_accounts
  (tenant_id, code, parent_id, name_ar, name_en, type, normal_side, is_postable, is_system, subledger, system_key)
select t.id, '4150', parent.id, 'خصومات المبيعات', 'Sales discounts', 'INCOME', 'DEBIT', true, true, 'VEHICLE',
       'SALES_DISCOUNTS'
  from public.tenants t
  join public.ledger_accounts parent on parent.tenant_id = t.id and parent.system_key = 'INCOME'
 where not exists (select 1 from public.ledger_accounts a where a.tenant_id = t.id and a.system_key = 'SALES_DISCOUNTS');

-- -----------------------------------------------------------------------------
-- One direct expense split over several cars (D-71 follow-up): each car's part
-- is an ordinary vehicle expense; the parts share a group id.
-- -----------------------------------------------------------------------------
alter table public.vehicle_expenses add column split_group_id uuid;
create index vehicle_expenses_split_group_idx on public.vehicle_expenses (tenant_id, split_group_id)
  where split_group_id is not null;

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
