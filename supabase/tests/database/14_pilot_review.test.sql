-- Pilot accountant review: Arabic and English make names match (Q-42); only the
-- owner and the manager cancel a consigned car's sale (Q-41); every showroom has
-- the sales-discounts account (P-12 revised).
begin;
set local search_path = public, extensions;
select plan(9);

select is(private.make_key('هيونداي'), private.make_key('Hyundai'), 'هيونداي is Hyundai');
select is(private.make_key('هيونداى'), private.make_key(' HYUNDAI '), 'ى/ي and case and spaces do not matter');
select is(private.make_key('مرسيدس بنز'), private.make_key('Mercedes-Benz'), 'multi-word names fold together');
select is(private.make_key('بي إم دبليو'), private.make_key('bmw'), 'hamza forms fold together');
select isnt(private.make_key('Honda'), private.make_key('Hyundai'), 'different makes stay different');
select is(private.make_key('Zotye'), private.make_key('zotye'), 'a make outside the catalogue matches its own spelling');

-- A request written in Arabic finds the seeded Hyundai Elantra (available, 480,000).
insert into public.customer_requests (id, tenant_id, customer_id, make, budget_max, created_by)
values ('00000000-0000-0000-0000-0000000c4001', '11111111-1111-1111-1111-111111111111',
        'd0000000-0000-0000-0000-000000000001', 'هيونداي', 500000, 'a0000000-0000-0000-0000-000000000001');
select private.match_request('00000000-0000-0000-0000-0000000c4001');
select ok(
  exists (select 1 from public.customer_request_matches
               where request_id = '00000000-0000-0000-0000-0000000c4001'
                 and vehicle_id = 'e1000000-0000-0000-0000-000000000001'),
  'an Arabic request matches an English make'
);

select results_eq(
  $$ select r.code from public.role_permissions rp join public.roles r on r.id = rp.role_id
      where rp.permission_code = 'sale.cancel_consigned' and r.tenant_id is null order by r.code $$,
  $$ values ('MANAGER'::text), ('OWNER') $$,
  'only the owner and the manager may cancel a consigned car''s sale'
);

select is(
  (select count(*)::int from public.tenants t
    where not exists (select 1 from public.ledger_accounts a
                       where a.tenant_id = t.id and a.system_key = 'SALES_DISCOUNTS' and a.code = '4150')),
  0, 'every showroom has 4150 sales discounts'
);

select * from finish();
rollback;
