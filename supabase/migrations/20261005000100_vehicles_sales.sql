-- =============================================================================
-- Phase 4: customers, suppliers, locations, vehicles (state machine, history,
-- media, documents), purchases, vehicle expenses, reservations and sales.
-- Design: SPEC §4.3, §4.6, §4.7, §10; docs/ERD.md §4-§6; ARCHITECTURE §5, §8;
-- ACCOUNTING rules 6-9, 11, 12, 26, 30-35, P-02, P-03, P-04, P-12;
-- DECISIONS D-05, D-06, D-15, D-23, D-26, D-28, D-34..D-36, D-41, D-68..D-79.
-- =============================================================================

-- -----------------------------------------------------------------------------
-- Customers (buyers, sellers, consignors in one table, A-06). Written only via
-- the API: phone normalisation and national-ID encryption happen there (D-68).
-- -----------------------------------------------------------------------------
create table public.customers (
  id                uuid primary key default gen_random_uuid(),
  tenant_id         uuid not null references public.tenants (id),
  name              text not null check (length(btrim(name)) > 0),
  phone_primary     text check (phone_primary ~ '^\+[0-9]{6,15}$'),
  phones            text[] not null default '{}',
  national_id_enc   text,
  national_id_last4 text check (national_id_last4 ~ '^[0-9A-Za-z]{1,4}$'),
  is_buyer          boolean not null default false,
  is_seller         boolean not null default false,
  is_consignor      boolean not null default false,
  address           text,
  notes             text,
  archived_at       timestamptz,
  created_at        timestamptz not null default now(),
  created_by        uuid,
  updated_at        timestamptz not null default now(),
  updated_by        uuid,
  unique (tenant_id, id),
  check ((national_id_enc is null) = (national_id_last4 is null))
);

create index customers_phone_idx on public.customers (tenant_id, phone_primary);
create index customers_name_trgm_idx on public.customers using gin (name extensions.gin_trgm_ops);

-- -----------------------------------------------------------------------------
-- Suppliers (D-23): workshops, transport, parts... with their own payable.
-- -----------------------------------------------------------------------------
create table public.suppliers (
  id          uuid primary key default gen_random_uuid(),
  tenant_id   uuid not null references public.tenants (id),
  name        text not null check (length(btrim(name)) > 0),
  kind        text not null default 'OTHER'
              check (kind in ('WORKSHOP', 'TRANSPORT', 'PARTS', 'AD_AGENCY', 'OTHER')),
  phone       text,
  notes       text,
  archived_at timestamptz,
  created_at  timestamptz not null default now(),
  created_by  uuid,
  updated_at  timestamptz not null default now(),
  updated_by  uuid,
  unique (tenant_id, id)
);

-- -----------------------------------------------------------------------------
-- Locations (D-46): yard, outdoor lot, workshop, external showroom, customer.
-- -----------------------------------------------------------------------------
create table public.locations (
  id          uuid primary key default gen_random_uuid(),
  tenant_id   uuid not null references public.tenants (id),
  branch_id   uuid,
  type        text not null
              check (type in ('BRANCH_YARD', 'OUTDOOR_LOT', 'WORKSHOP', 'EXTERNAL_SHOWROOM', 'CUSTOMER')),
  name_ar     text not null check (length(btrim(name_ar)) > 0),
  name_en     text,
  is_default  boolean not null default false,
  archived_at timestamptz,
  created_at  timestamptz not null default now(),
  created_by  uuid,
  updated_at  timestamptz not null default now(),
  updated_by  uuid,
  unique (tenant_id, id),
  foreign key (tenant_id, branch_id) references public.branches (tenant_id, id)
);

create unique index locations_one_default_idx on public.locations (tenant_id) where is_default and archived_at is null;

create or replace function private.seed_tenant_locations(p_tenant uuid)
returns void
language sql
security definer
set search_path = ''
as $$
  insert into public.locations (tenant_id, type, name_ar, name_en, is_default)
  select p_tenant, l.type, l.name_ar, l.name_en, l.is_default
    from (values
      ('BRANCH_YARD', 'المعرض',     'Showroom',     true),
      ('WORKSHOP',    'الورشة',      'Workshop',     false),
      ('CUSTOMER',    'عند العميل', 'With customer', false)
    ) as l (type, name_ar, name_en, is_default)
   where not exists (select 1 from public.locations x where x.tenant_id = p_tenant);
$$;

create or replace function private.seed_tenant_locations_trigger()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
  perform private.seed_tenant_locations(new.id);
  return null;
end;
$$;

create trigger tenants_seed_locations
  after insert on public.tenants
  for each row execute function private.seed_tenant_locations_trigger();

select private.seed_tenant_locations(id) from public.tenants;

-- -----------------------------------------------------------------------------
-- Vehicles (SPEC §4.3). All writes go through the API (D-06); the status
-- lifecycle is enforced here as well as in the service. Cost is never stored:
-- it is the vehicle's balance on account 1300 (D-26).
-- -----------------------------------------------------------------------------
create table public.vehicles (
  id                   uuid primary key default gen_random_uuid(),
  tenant_id            uuid not null references public.tenants (id),
  stock_no             text not null,
  vin                  text,
  vin_normalized       text,
  plate_no             text,
  make                 text not null check (length(btrim(make)) > 0),
  model                text not null check (length(btrim(model)) > 0),
  trim                 text,
  year                 smallint check (year between 1950 and 2100),
  color_ext            text,
  color_int            text,
  body_type            text,
  transmission         text check (transmission in ('AUTOMATIC', 'MANUAL', 'CVT', 'OTHER')),
  fuel                 text check (fuel in ('PETROL', 'DIESEL', 'HYBRID', 'ELECTRIC', 'NATURAL_GAS', 'OTHER')),
  engine_cc            integer check (engine_cc between 0 and 20000),
  mileage_km           integer check (mileage_km >= 0),
  license_expiry       date,
  license_governorate  text,
  ownership_type       text not null default 'OWNED' check (ownership_type in ('OWNED', 'CONSIGNED_IN')),
  acquisition_source   text not null default 'DIRECT_PURCHASE'
                       check (acquisition_source in ('DIRECT_PURCHASE', 'TRADE_IN', 'CONSIGNMENT_IN', 'AUCTION', 'IMPORT')),
  status               text not null default 'DRAFT'
                       check (status in ('DRAFT', 'IN_PREPARATION', 'AVAILABLE', 'RESERVED', 'SOLD', 'DELIVERED',
                                         'AT_OTHER_SHOWROOM', 'RETURNED_TO_OWNER', 'ARCHIVED')),
  current_location_id  uuid,
  asking_price         numeric(18, 2) check (asking_price >= 0),
  min_price            numeric(18, 2) check (min_price >= 0),
  stock_date           date,
  last_price_change_at timestamptz,
  notes                text,
  archived_at          timestamptz,
  created_at           timestamptz not null default now(),
  created_by           uuid,
  updated_at           timestamptz not null default now(),
  updated_by           uuid,
  unique (tenant_id, id),
  unique (tenant_id, stock_no),
  foreign key (tenant_id, current_location_id) references public.locations (tenant_id, id),
  check ((status = 'ARCHIVED') = (archived_at is not null))
);

-- VIN unique among vehicles still with the showroom (D-69): a delivered car may
-- come back later, e.g. as a trade-in.
create unique index vehicles_vin_active_idx on public.vehicles (tenant_id, vin_normalized)
  where vin_normalized is not null and archived_at is null and status not in ('DELIVERED', 'RETURNED_TO_OWNER');
create index vehicles_status_idx on public.vehicles (tenant_id, status, stock_date);
create index vehicles_make_idx on public.vehicles (tenant_id, make, model, year);
create index vehicles_vin_trgm_idx on public.vehicles using gin (vin_normalized extensions.gin_trgm_ops);
create index vehicles_plate_trgm_idx on public.vehicles using gin (plate_no extensions.gin_trgm_ops);

create table public.vehicle_status_history (
  id          uuid primary key default gen_random_uuid(),
  tenant_id   uuid not null references public.tenants (id),
  vehicle_id  uuid not null,
  from_status text,
  to_status   text not null,
  changed_at  timestamptz not null default clock_timestamp(),
  changed_by  uuid,
  reason      text,
  unique (tenant_id, id),
  foreign key (tenant_id, vehicle_id) references public.vehicles (tenant_id, id)
);
create index vehicle_status_history_idx on public.vehicle_status_history (tenant_id, vehicle_id, changed_at);

create table public.vehicle_location_history (
  id               uuid primary key default gen_random_uuid(),
  tenant_id        uuid not null references public.tenants (id),
  vehicle_id       uuid not null,
  from_location_id uuid,
  to_location_id   uuid,
  moved_at         timestamptz not null default clock_timestamp(),
  moved_by         uuid,
  reason           text,
  unique (tenant_id, id),
  foreign key (tenant_id, vehicle_id) references public.vehicles (tenant_id, id),
  foreign key (tenant_id, from_location_id) references public.locations (tenant_id, id),
  foreign key (tenant_id, to_location_id) references public.locations (tenant_id, id)
);
create index vehicle_location_history_idx on public.vehicle_location_history (tenant_id, vehicle_id, moved_at);

create table public.vehicle_price_history (
  id           uuid primary key default gen_random_uuid(),
  tenant_id    uuid not null references public.tenants (id),
  vehicle_id   uuid not null,
  asking_price numeric(18, 2),
  min_price    numeric(18, 2),
  changed_at   timestamptz not null default clock_timestamp(),
  changed_by   uuid,
  unique (tenant_id, id),
  foreign key (tenant_id, vehicle_id) references public.vehicles (tenant_id, id)
);
create index vehicle_price_history_idx on public.vehicle_price_history (tenant_id, vehicle_id, changed_at);

-- Photos (private bucket vehicle-media, D-15). Removed photos are archived.
create table public.vehicle_media (
  id           uuid primary key default gen_random_uuid(),
  tenant_id    uuid not null references public.tenants (id),
  vehicle_id   uuid not null,
  storage_path text not null,
  kind         text not null default 'PHOTO' check (kind in ('PHOTO')),
  content_type text not null,
  size_bytes   integer not null check (size_bytes > 0),
  sort_order   integer not null default 0,
  archived_at  timestamptz,
  created_at   timestamptz not null default now(),
  created_by   uuid,
  updated_at   timestamptz not null default now(),
  updated_by   uuid,
  unique (tenant_id, id),
  unique (storage_path),
  foreign key (tenant_id, vehicle_id) references public.vehicles (tenant_id, id)
);
create index vehicle_media_vehicle_idx on public.vehicle_media (tenant_id, vehicle_id, sort_order);

-- Generic attachments (ERD §8). Cost-bearing documents are hidden from anyone
-- without vehicle.view_cost (G-09); purchase contracts and seller receipts are
-- always cost-sensitive.
create table public.documents (
  id           uuid primary key default gen_random_uuid(),
  tenant_id    uuid not null references public.tenants (id),
  entity_type  text not null check (entity_type in ('VEHICLE', 'CUSTOMER', 'SALE', 'SUPPLIER')),
  entity_id    uuid not null,
  doc_type     text not null check (doc_type in ('LICENSE', 'PURCHASE_CONTRACT', 'SELLER_RECEIPT',
                                                 'INSPECTION_REPORT', 'SALE_CONTRACT', 'ID_COPY', 'OTHER')),
  storage_path text not null,
  file_name    text not null,
  content_type text not null,
  size_bytes   integer not null check (size_bytes > 0),
  sensitivity  text not null default 'NORMAL' check (sensitivity in ('NORMAL', 'COST')),
  archived_at  timestamptz,
  created_at   timestamptz not null default now(),
  created_by   uuid,
  updated_at   timestamptz not null default now(),
  updated_by   uuid,
  unique (tenant_id, id),
  unique (storage_path),
  check (doc_type not in ('PURCHASE_CONTRACT', 'SELLER_RECEIPT') or sensitivity = 'COST')
);
create index documents_entity_idx on public.documents (tenant_id, entity_type, entity_id);

-- -----------------------------------------------------------------------------
-- Purchase (rules 6, 7) and later payments to the seller (rule 8). A trade-in
-- also creates a purchase record, posted inside the sale entry (rule 26).
-- -----------------------------------------------------------------------------
create table public.vehicle_purchases (
  id                 uuid primary key default gen_random_uuid(),
  tenant_id          uuid not null references public.tenants (id),
  vehicle_id         uuid not null,
  seller_customer_id uuid not null,
  source             text not null default 'PURCHASE' check (source in ('PURCHASE', 'TRADE_IN')),
  purchase_date      date not null,
  price              numeric(18, 2) not null check (price > 0),
  deferred_amount    numeric(18, 2) not null default 0 check (deferred_amount >= 0 and deferred_amount <= price),
  notes              text,
  status             text not null default 'POSTED' check (status in ('POSTED', 'REVERSED')),
  journal_entry_id   uuid not null,
  reversal_entry_id  uuid,
  created_at         timestamptz not null default now(),
  created_by         uuid,
  updated_at         timestamptz not null default now(),
  updated_by         uuid,
  unique (tenant_id, id),
  foreign key (tenant_id, vehicle_id) references public.vehicles (tenant_id, id),
  foreign key (tenant_id, seller_customer_id) references public.customers (tenant_id, id),
  foreign key (tenant_id, journal_entry_id) references public.journal_entries (tenant_id, id),
  foreign key (tenant_id, reversal_entry_id) references public.journal_entries (tenant_id, id),
  check ((status = 'REVERSED') = (reversal_entry_id is not null))
);
create unique index vehicle_purchases_one_posted_idx on public.vehicle_purchases (tenant_id, vehicle_id)
  where status = 'POSTED';

create table public.purchase_payments (
  id              uuid primary key default gen_random_uuid(),
  tenant_id       uuid not null references public.tenants (id),
  purchase_id     uuid not null,
  cash_account_id uuid not null,
  amount          numeric(18, 2) not null check (amount > 0),
  created_at      timestamptz not null default now(),
  created_by      uuid,
  updated_at      timestamptz not null default now(),
  updated_by      uuid,
  unique (tenant_id, id),
  foreign key (tenant_id, purchase_id) references public.vehicle_purchases (tenant_id, id),
  foreign key (tenant_id, cash_account_id) references public.cash_accounts (tenant_id, id)
);

create table public.seller_payments (
  id                uuid primary key default gen_random_uuid(),
  tenant_id         uuid not null references public.tenants (id),
  purchase_id       uuid not null,
  payment_date      date not null,
  amount            numeric(18, 2) not null check (amount > 0),
  cash_account_id   uuid not null,
  notes             text,
  status            text not null default 'POSTED' check (status in ('POSTED', 'REVERSED')),
  journal_entry_id  uuid not null,
  reversal_entry_id uuid,
  created_at        timestamptz not null default now(),
  created_by        uuid,
  updated_at        timestamptz not null default now(),
  updated_by        uuid,
  unique (tenant_id, id),
  foreign key (tenant_id, purchase_id) references public.vehicle_purchases (tenant_id, id),
  foreign key (tenant_id, cash_account_id) references public.cash_accounts (tenant_id, id),
  foreign key (tenant_id, journal_entry_id) references public.journal_entries (tenant_id, id),
  foreign key (tenant_id, reversal_entry_id) references public.journal_entries (tenant_id, id),
  check ((status = 'REVERSED') = (reversal_entry_id is not null))
);

-- -----------------------------------------------------------------------------
-- Vehicle expenses: rule 9 (cash), 30 (partner), 31 (supplier credit); on a
-- sold car the cost goes to COGS (P-04, approved under Q-26).
-- -----------------------------------------------------------------------------
create table public.vehicle_expenses (
  id                   uuid primary key default gen_random_uuid(),
  tenant_id            uuid not null references public.tenants (id),
  vehicle_id           uuid not null,
  category_id          uuid not null,
  expense_date         date not null,
  amount               numeric(18, 2) not null check (amount > 0),
  description          text,
  funding              text not null check (funding in ('CASH_ACCOUNT', 'SUPPLIER_CREDIT', 'PARTNER')),
  cash_account_id      uuid,
  supplier_id          uuid,
  paid_by_partner_id   uuid,
  partner_funding_mode text check (partner_funding_mode in ('CURRENT_ACCOUNT', 'LOAN')),
  treatment            text not null default 'CAPITALIZE' check (treatment in ('CAPITALIZE', 'COGS')),
  status               text not null default 'POSTED' check (status in ('POSTED', 'REVERSED')),
  journal_entry_id     uuid not null,
  reversal_entry_id    uuid,
  created_at           timestamptz not null default now(),
  created_by           uuid,
  updated_at           timestamptz not null default now(),
  updated_by           uuid,
  unique (tenant_id, id),
  foreign key (tenant_id, vehicle_id) references public.vehicles (tenant_id, id),
  foreign key (tenant_id, category_id) references public.expense_categories (tenant_id, id),
  foreign key (tenant_id, cash_account_id) references public.cash_accounts (tenant_id, id),
  foreign key (tenant_id, supplier_id) references public.suppliers (tenant_id, id),
  foreign key (tenant_id, paid_by_partner_id) references public.partners (tenant_id, id),
  foreign key (tenant_id, journal_entry_id) references public.journal_entries (tenant_id, id),
  foreign key (tenant_id, reversal_entry_id) references public.journal_entries (tenant_id, id),
  check ((status = 'REVERSED') = (reversal_entry_id is not null)),
  constraint vehicle_expenses_one_funding check (
    (funding = 'CASH_ACCOUNT' and cash_account_id is not null and supplier_id is null
       and paid_by_partner_id is null and partner_funding_mode is null)
    or (funding = 'SUPPLIER_CREDIT' and supplier_id is not null and cash_account_id is null
       and paid_by_partner_id is null and partner_funding_mode is null)
    or (funding = 'PARTNER' and paid_by_partner_id is not null and partner_funding_mode is not null
       and cash_account_id is null and supplier_id is null)
  )
);
create index vehicle_expenses_vehicle_idx on public.vehicle_expenses (tenant_id, vehicle_id, expense_date);

-- General expenses on supplier credit (rule 31).
alter table public.general_expenses
  add column supplier_id uuid,
  add constraint general_expenses_supplier_fk
    foreign key (tenant_id, supplier_id) references public.suppliers (tenant_id, id),
  drop constraint general_expenses_one_funding,
  add constraint general_expenses_one_funding check (
    (cash_account_id is not null and supplier_id is null and paid_by_partner_id is null and partner_funding_mode is null)
    or (supplier_id is not null and cash_account_id is null and paid_by_partner_id is null and partner_funding_mode is null)
    or (paid_by_partner_id is not null and partner_funding_mode is not null and cash_account_id is null
        and supplier_id is null)
  );

-- Payments to suppliers (rule 32).
create table public.supplier_payments (
  id                uuid primary key default gen_random_uuid(),
  tenant_id         uuid not null references public.tenants (id),
  supplier_id       uuid not null,
  payment_date      date not null,
  amount            numeric(18, 2) not null check (amount > 0),
  cash_account_id   uuid not null,
  notes             text,
  status            text not null default 'POSTED' check (status in ('POSTED', 'REVERSED')),
  journal_entry_id  uuid not null,
  reversal_entry_id uuid,
  created_at        timestamptz not null default now(),
  created_by        uuid,
  updated_at        timestamptz not null default now(),
  updated_by        uuid,
  unique (tenant_id, id),
  foreign key (tenant_id, supplier_id) references public.suppliers (tenant_id, id),
  foreign key (tenant_id, cash_account_id) references public.cash_accounts (tenant_id, id),
  foreign key (tenant_id, journal_entry_id) references public.journal_entries (tenant_id, id),
  foreign key (tenant_id, reversal_entry_id) references public.journal_entries (tenant_id, id),
  check ((status = 'REVERSED') = (reversal_entry_id is not null))
);

-- -----------------------------------------------------------------------------
-- Reservations and deposits (rules 11, 34, 35). RELEASED: the vehicle is free
-- again (its sale was cancelled with the MIRROR method) but the deposit is
-- still held until it is refunded or forfeited (D-72).
-- -----------------------------------------------------------------------------
create table public.reservations (
  id                     uuid primary key default gen_random_uuid(),
  tenant_id              uuid not null references public.tenants (id),
  vehicle_id             uuid not null,
  customer_id            uuid not null,
  reservation_date       date not null,
  deposit_amount         numeric(18, 2) not null check (deposit_amount > 0),
  cash_account_id        uuid not null,
  expires_on             date,
  notes                  text,
  status                 text not null default 'ACTIVE'
                         check (status in ('ACTIVE', 'RELEASED', 'APPLIED', 'REFUNDED', 'FORFEITED')),
  journal_entry_id       uuid not null,
  settled_on             date,
  settle_cash_account_id uuid,
  settle_entry_id        uuid,
  sale_id                uuid,
  created_at             timestamptz not null default now(),
  created_by             uuid,
  updated_at             timestamptz not null default now(),
  updated_by             uuid,
  unique (tenant_id, id),
  foreign key (tenant_id, vehicle_id) references public.vehicles (tenant_id, id),
  foreign key (tenant_id, customer_id) references public.customers (tenant_id, id),
  foreign key (tenant_id, cash_account_id) references public.cash_accounts (tenant_id, id),
  foreign key (tenant_id, settle_cash_account_id) references public.cash_accounts (tenant_id, id),
  foreign key (tenant_id, journal_entry_id) references public.journal_entries (tenant_id, id),
  foreign key (tenant_id, settle_entry_id) references public.journal_entries (tenant_id, id),
  check (expires_on is null or expires_on >= reservation_date),
  check ((status in ('REFUNDED', 'FORFEITED')) = (settle_entry_id is not null))
);
create unique index reservations_one_active_idx on public.reservations (tenant_id, vehicle_id) where status = 'ACTIVE';

-- -----------------------------------------------------------------------------
-- Sales (SPEC §4.7). Draft -> posted -> cancelled. The sale price is the net
-- price after discount (P-12). Profit is never stored (D-34).
-- -----------------------------------------------------------------------------
create table public.sales (
  id                           uuid primary key default gen_random_uuid(),
  tenant_id                    uuid not null references public.tenants (id),
  sale_no                      text not null,
  vehicle_id                   uuid not null,
  buyer_customer_id            uuid not null,
  channel                      text not null default 'DIRECT' check (channel in ('DIRECT', 'EXTERNAL_SHOWROOM')),
  sale_date                    date not null,
  list_price                   numeric(18, 2) not null check (list_price > 0),
  discount                     numeric(18, 2) not null default 0 check (discount >= 0),
  sale_price                   numeric(18, 2) not null check (sale_price > 0),
  reservation_id               uuid,
  deposit_applied              numeric(18, 2) not null default 0 check (deposit_applied >= 0),
  trade_in_value               numeric(18, 2) not null default 0 check (trade_in_value >= 0),
  trade_in                     jsonb,
  trade_in_vehicle_id          uuid,
  status                       text not null default 'DRAFT' check (status in ('DRAFT', 'POSTED', 'CANCELLED')),
  posted_at                    timestamptz,
  posted_by                    uuid,
  journal_entry_id             uuid,
  cost_journal_entry_id        uuid,
  invoice_no                   text,
  einvoice_status              text not null default 'NOT_APPLICABLE'
                               check (einvoice_status in ('NOT_APPLICABLE', 'NOT_SUBMITTED', 'SUBMITTED', 'VALID',
                                                          'INVALID', 'CANCELLED')),
  einvoice_uuid                text,
  cancellation_method          text check (cancellation_method in ('REFUND_LIABILITY', 'MIRROR')),
  cancel_date                  date,
  cancel_reason                text,
  cancelled_at                 timestamptz,
  cancelled_by                 uuid,
  cancel_journal_entry_id      uuid,
  cancel_cost_journal_entry_id uuid,
  notes                        text,
  created_at                   timestamptz not null default now(),
  created_by                   uuid,
  updated_at                   timestamptz not null default now(),
  updated_by                   uuid,
  unique (tenant_id, id),
  unique (tenant_id, sale_no),
  foreign key (tenant_id, vehicle_id) references public.vehicles (tenant_id, id),
  foreign key (tenant_id, buyer_customer_id) references public.customers (tenant_id, id),
  foreign key (tenant_id, reservation_id) references public.reservations (tenant_id, id),
  foreign key (tenant_id, trade_in_vehicle_id) references public.vehicles (tenant_id, id),
  foreign key (tenant_id, journal_entry_id) references public.journal_entries (tenant_id, id),
  foreign key (tenant_id, cost_journal_entry_id) references public.journal_entries (tenant_id, id),
  foreign key (tenant_id, cancel_journal_entry_id) references public.journal_entries (tenant_id, id),
  foreign key (tenant_id, cancel_cost_journal_entry_id) references public.journal_entries (tenant_id, id),
  check (sale_price = list_price - discount),
  check ((trade_in_value > 0) = (trade_in is not null)),
  check (status = 'DRAFT' or (journal_entry_id is not null and cost_journal_entry_id is not null
                              and invoice_no is not null and posted_at is not null)),
  check ((status = 'CANCELLED') = (cancelled_at is not null and cancel_reason is not null
                                   and cancel_journal_entry_id is not null))
);

-- Business rule 1: a vehicle is sold once, unless that sale was cancelled.
create unique index sales_one_posted_per_vehicle_idx on public.sales (tenant_id, vehicle_id) where status = 'POSTED';
create unique index sales_invoice_no_idx on public.sales (tenant_id, invoice_no) where invoice_no is not null;
create index sales_date_idx on public.sales (tenant_id, sale_date);
create index sales_buyer_idx on public.sales (tenant_id, buyer_customer_id);

alter table public.reservations
  add constraint reservations_sale_fk foreign key (tenant_id, sale_id) references public.sales (tenant_id, id);

create table public.sale_payments (
  id                uuid primary key default gen_random_uuid(),
  tenant_id         uuid not null references public.tenants (id),
  sale_id           uuid not null,
  line_no           smallint not null default 1 check (line_no > 0),
  cash_account_id   uuid not null,
  payment_method_id uuid,
  amount            numeric(18, 2) not null check (amount > 0),
  reference         text,
  created_at        timestamptz not null default now(),
  created_by        uuid,
  updated_at        timestamptz not null default now(),
  updated_by        uuid,
  unique (tenant_id, id),
  foreign key (tenant_id, sale_id) references public.sales (tenant_id, id) on delete cascade,
  foreign key (tenant_id, cash_account_id) references public.cash_accounts (tenant_id, id),
  foreign key (tenant_id, payment_method_id) references public.payment_methods (tenant_id, id)
);
create index sale_payments_sale_idx on public.sale_payments (tenant_id, sale_id);

-- Refunds of customer credit (P-02 / P-03 refund leg): Dr 2310 / Cr cash.
create table public.customer_refunds (
  id                uuid primary key default gen_random_uuid(),
  tenant_id         uuid not null references public.tenants (id),
  customer_id       uuid not null,
  refund_date       date not null,
  amount            numeric(18, 2) not null check (amount > 0),
  cash_account_id   uuid not null,
  notes             text,
  status            text not null default 'POSTED' check (status in ('POSTED', 'REVERSED')),
  journal_entry_id  uuid not null,
  reversal_entry_id uuid,
  created_at        timestamptz not null default now(),
  created_by        uuid,
  updated_at        timestamptz not null default now(),
  updated_by        uuid,
  unique (tenant_id, id),
  foreign key (tenant_id, customer_id) references public.customers (tenant_id, id),
  foreign key (tenant_id, cash_account_id) references public.cash_accounts (tenant_id, id),
  foreign key (tenant_id, journal_entry_id) references public.journal_entries (tenant_id, id),
  foreign key (tenant_id, reversal_entry_id) references public.journal_entries (tenant_id, id),
  check ((status = 'REVERSED') = (reversal_entry_id is not null))
);

-- -----------------------------------------------------------------------------
-- Journal subledgers now reference real customers, vehicles and suppliers.
-- -----------------------------------------------------------------------------
alter table public.journal_lines
  add constraint journal_lines_customer_fk
    foreign key (tenant_id, customer_id) references public.customers (tenant_id, id),
  add constraint journal_lines_vehicle_fk
    foreign key (tenant_id, vehicle_id) references public.vehicles (tenant_id, id),
  add constraint journal_lines_supplier_fk
    foreign key (tenant_id, supplier_id) references public.suppliers (tenant_id, id);

-- Invoice numbering per country pack (D-16): {prefix}-{YYYY}-{seq:05}.
alter table public.country_packs add column invoice_prefix text not null default 'INV'
  check (invoice_prefix ~ '^[A-Z]{2,6}$');

-- -----------------------------------------------------------------------------
-- Vehicle triggers: stock number, VIN normalisation, state machine, history.
-- -----------------------------------------------------------------------------
create or replace function private.next_counter(p_tenant uuid, p_key text)
returns bigint
language sql
security definer
set search_path = ''
as $$
  insert into public.tenant_counters as c (tenant_id, counter_key, last_value)
  values (p_tenant, p_key, 1)
  on conflict (tenant_id, counter_key) do update set last_value = c.last_value + 1
  returning c.last_value;
$$;

-- The lifecycle of SPEC §4.3 / ERD §5. RETURNED_TO_OWNER is for consigned-in cars only.
create or replace function private.vehicle_transition_allowed(p_from text, p_to text, p_ownership text)
returns boolean
language sql
immutable
set search_path = ''
as $$
  select case
    when p_to = 'RETURNED_TO_OWNER' then
      p_ownership = 'CONSIGNED_IN' and p_from in ('IN_PREPARATION', 'AVAILABLE', 'RESERVED')
    else (p_from || '>' || p_to) = any (array[
      'DRAFT>IN_PREPARATION', 'IN_PREPARATION>AVAILABLE',
      'AVAILABLE>RESERVED', 'RESERVED>AVAILABLE', 'RESERVED>SOLD', 'AVAILABLE>SOLD',
      'IN_PREPARATION>AT_OTHER_SHOWROOM', 'AVAILABLE>AT_OTHER_SHOWROOM',
      'AT_OTHER_SHOWROOM>AVAILABLE', 'AT_OTHER_SHOWROOM>SOLD',
      'SOLD>DELIVERED', 'SOLD>AVAILABLE',
      'DRAFT>ARCHIVED', 'IN_PREPARATION>ARCHIVED', 'AVAILABLE>ARCHIVED'])
  end;
$$;

create or replace function private.vehicle_before_insert()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
  if new.status <> 'DRAFT' then
    raise exception 'a vehicle starts as DRAFT' using errcode = 'SR020', detail = format('>%s', new.status);
  end if;
  if new.stock_no is null or new.stock_no = '' then
    new.stock_no := format('V-%s-%s', to_char(now(), 'YYYY'),
                           lpad(private.next_counter(new.tenant_id, 'stock-' || to_char(now(), 'YYYY'))::text, 4, '0'));
  end if;
  new.vin_normalized := nullif(upper(regexp_replace(coalesce(new.vin, ''), '[^A-Za-z0-9]', '', 'g')), '');
  if new.asking_price is not null or new.min_price is not null then
    new.last_price_change_at := now();
  end if;
  return new;
end;
$$;

create or replace function private.vehicle_after_insert()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
  insert into public.vehicle_status_history (tenant_id, vehicle_id, from_status, to_status, changed_by, reason)
  values (new.tenant_id, new.id, null, new.status, private.current_actor_id(),
          nullif(current_setting('app.change_reason', true), ''));
  if new.current_location_id is not null then
    insert into public.vehicle_location_history (tenant_id, vehicle_id, from_location_id, to_location_id, moved_by)
    values (new.tenant_id, new.id, null, new.current_location_id, private.current_actor_id());
  end if;
  if new.asking_price is not null or new.min_price is not null then
    insert into public.vehicle_price_history (tenant_id, vehicle_id, asking_price, min_price, changed_by)
    values (new.tenant_id, new.id, new.asking_price, new.min_price, private.current_actor_id());
  end if;
  return null;
end;
$$;

create or replace function private.vehicle_before_update()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_reason text := nullif(current_setting('app.change_reason', true), '');
begin
  if new.stock_no is distinct from old.stock_no or new.ownership_type is distinct from old.ownership_type
     or new.tenant_id is distinct from old.tenant_id then
    raise exception 'stock number and ownership type cannot change' using errcode = 'SR003';
  end if;
  if old.status = 'ARCHIVED' and new.status = 'ARCHIVED' and (to_jsonb(new) - array['updated_at', 'updated_by'])
       <> (to_jsonb(old) - array['updated_at', 'updated_by']) then
    raise exception 'an archived vehicle cannot be changed' using errcode = 'SR003';
  end if;
  new.vin_normalized := nullif(upper(regexp_replace(coalesce(new.vin, ''), '[^A-Za-z0-9]', '', 'g')), '');

  if new.status is distinct from old.status then
    if not private.vehicle_transition_allowed(old.status, new.status, old.ownership_type) then
      raise exception 'vehicle cannot move from % to %', old.status, new.status
        using errcode = 'SR020', detail = format('%s>%s', old.status, new.status);
    end if;
    -- SOLD only with a posted sale; back from SOLD only when no posted sale remains (business rule 1).
    if new.status = 'SOLD' and not exists (
         select 1 from public.sales s where s.tenant_id = new.tenant_id and s.vehicle_id = new.id and s.status = 'POSTED') then
      raise exception 'a vehicle is SOLD only through a posted sale' using errcode = 'SR020',
        detail = format('%s>%s', old.status, new.status);
    end if;
    if old.status = 'SOLD' and new.status = 'AVAILABLE' and exists (
         select 1 from public.sales s where s.tenant_id = new.tenant_id and s.vehicle_id = new.id and s.status = 'POSTED') then
      raise exception 'cancel the sale first' using errcode = 'SR020', detail = format('%s>%s', old.status, new.status);
    end if;
    new.archived_at := case when new.status = 'ARCHIVED' then now() end;
    insert into public.vehicle_status_history (tenant_id, vehicle_id, from_status, to_status, changed_by, reason)
    values (new.tenant_id, new.id, old.status, new.status, private.current_actor_id(), v_reason);
  end if;

  if new.current_location_id is distinct from old.current_location_id then
    insert into public.vehicle_location_history (tenant_id, vehicle_id, from_location_id, to_location_id, moved_by, reason)
    values (new.tenant_id, new.id, old.current_location_id, new.current_location_id, private.current_actor_id(), v_reason);
  end if;

  if new.asking_price is distinct from old.asking_price or new.min_price is distinct from old.min_price then
    new.last_price_change_at := now();
    insert into public.vehicle_price_history (tenant_id, vehicle_id, asking_price, min_price, changed_by)
    values (new.tenant_id, new.id, new.asking_price, new.min_price, private.current_actor_id());
  end if;
  return new;
end;
$$;

create trigger vehicles_before_insert before insert on public.vehicles
  for each row execute function private.vehicle_before_insert();
create trigger vehicles_after_insert after insert on public.vehicles
  for each row execute function private.vehicle_after_insert();
create trigger vehicles_before_update before update on public.vehicles
  for each row execute function private.vehicle_before_update();
create trigger vehicles_no_delete before delete on public.vehicles
  for each row execute function private.journal_forbid_change();

-- History is append-only.
create trigger vehicle_status_history_no_change before update or delete on public.vehicle_status_history
  for each row execute function private.journal_forbid_change();
create trigger vehicle_location_history_no_change before update or delete on public.vehicle_location_history
  for each row execute function private.journal_forbid_change();
create trigger vehicle_price_history_no_change before update or delete on public.vehicle_price_history
  for each row execute function private.journal_forbid_change();

-- -----------------------------------------------------------------------------
-- Posted documents only move POSTED -> REVERSED with their reversal entry.
-- -----------------------------------------------------------------------------
create trigger vehicle_purchases_before_update before update on public.vehicle_purchases
  for each row execute function private.posted_document_before_update();
create trigger seller_payments_before_update before update on public.seller_payments
  for each row execute function private.posted_document_before_update();
create trigger vehicle_expenses_before_update before update on public.vehicle_expenses
  for each row execute function private.posted_document_before_update();
create trigger supplier_payments_before_update before update on public.supplier_payments
  for each row execute function private.posted_document_before_update();
create trigger customer_refunds_before_update before update on public.customer_refunds
  for each row execute function private.posted_document_before_update();
create trigger purchase_payments_no_change before update or delete on public.purchase_payments
  for each row execute function private.journal_forbid_change();

-- Reservations: amounts and links never change; only the status moves forward.
create or replace function private.reservation_before_update()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  if (to_jsonb(new) - array['status', 'settled_on', 'settle_cash_account_id', 'settle_entry_id', 'sale_id',
                            'updated_at', 'updated_by'])
     <> (to_jsonb(old) - array['status', 'settled_on', 'settle_cash_account_id', 'settle_entry_id', 'sale_id',
                               'updated_at', 'updated_by'])
     or old.status in ('REFUNDED', 'FORFEITED')
     or (old.status || '>' || new.status) not in (
          'ACTIVE>ACTIVE', 'ACTIVE>APPLIED', 'ACTIVE>REFUNDED', 'ACTIVE>FORFEITED',
          'APPLIED>APPLIED', 'APPLIED>RELEASED', 'RELEASED>RELEASED', 'RELEASED>REFUNDED', 'RELEASED>FORFEITED') then
    raise exception 'reservation cannot change like this' using errcode = 'SR003';
  end if;
  return new;
end;
$$;

create trigger reservations_before_update before update on public.reservations
  for each row execute function private.reservation_before_update();

-- Sales: drafts are editable (and deletable); a posted sale only moves to
-- CANCELLED with its cancellation entries; a cancelled sale never changes.
create or replace function private.sale_before_change()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  if tg_op = 'DELETE' then
    if old.status <> 'DRAFT' then
      raise exception 'only draft sales can be deleted' using errcode = 'SR003';
    end if;
    return old;
  end if;
  if old.status = 'DRAFT' then
    return new;
  end if;
  if old.status = 'POSTED' and new.status = 'POSTED'
     and (to_jsonb(new) - array['einvoice_status', 'einvoice_uuid', 'updated_at', 'updated_by'])
       = (to_jsonb(old) - array['einvoice_status', 'einvoice_uuid', 'updated_at', 'updated_by']) then
    return new;
  end if;
  if old.status = 'POSTED' and new.status = 'CANCELLED'
     and (to_jsonb(new) - array['status', 'cancellation_method', 'cancel_date', 'cancel_reason', 'cancelled_at',
                                'cancelled_by', 'cancel_journal_entry_id', 'cancel_cost_journal_entry_id',
                                'updated_at', 'updated_by'])
       = (to_jsonb(old) - array['status', 'cancellation_method', 'cancel_date', 'cancel_reason', 'cancelled_at',
                                'cancelled_by', 'cancel_journal_entry_id', 'cancel_cost_journal_entry_id',
                                'updated_at', 'updated_by']) then
    return new;
  end if;
  raise exception 'posted sales cannot be changed; cancel them instead' using errcode = 'SR003';
end;
$$;

create trigger sales_before_update before update or delete on public.sales
  for each row execute function private.sale_before_change();

create or replace function private.sale_payment_before_change()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_status text;
begin
  select status into v_status from public.sales
   where id = coalesce(new.sale_id, old.sale_id) and tenant_id = coalesce(new.tenant_id, old.tenant_id);
  -- A cascade from a deleted draft finds no parent row any more.
  if v_status is not null and v_status <> 'DRAFT' then
    raise exception 'payments of a posted sale cannot change' using errcode = 'SR003';
  end if;
  return coalesce(new, old);
end;
$$;

create trigger sale_payments_before_change before insert or update or delete on public.sale_payments
  for each row execute function private.sale_payment_before_change();

-- -----------------------------------------------------------------------------
-- Catalog view for everyone with vehicle.view: no purchase price, no minimum
-- price, no cost (ARCHITECTURE §5). It runs with its owner's rights because
-- the base table is denied to sales; rows are filtered by permission here.
-- -----------------------------------------------------------------------------
create view public.vehicles_catalog
with (security_invoker = false)
as
select v.id, v.tenant_id, v.stock_no, v.vin, v.plate_no, v.make, v.model, v.trim, v.year, v.color_ext, v.color_int,
       v.body_type, v.transmission, v.fuel, v.engine_cc, v.mileage_km, v.license_expiry, v.license_governorate,
       v.ownership_type, v.acquisition_source, v.status, v.current_location_id, v.asking_price, v.stock_date,
       v.last_price_change_at, v.notes, v.archived_at, v.created_at, v.updated_at
  from public.vehicles v
 where v.tenant_id = any ((select private.tenants_with_permission('vehicle.view'))::uuid[]);

revoke all on public.vehicles_catalog from anon, authenticated, service_role, app_api;
grant select on public.vehicles_catalog to authenticated;

-- -----------------------------------------------------------------------------
-- Security.
-- -----------------------------------------------------------------------------
call private.secure_table('public.customers');
call private.secure_table('public.suppliers');
call private.secure_table('public.locations');
call private.secure_table('public.vehicles');
call private.secure_table('public.vehicle_status_history', p_touch => false, p_audit => false);
call private.secure_table('public.vehicle_location_history', p_touch => false, p_audit => false);
call private.secure_table('public.vehicle_price_history', p_touch => false, p_audit => false);
call private.secure_table('public.vehicle_media');
call private.secure_table('public.documents');
call private.secure_table('public.vehicle_purchases');
call private.secure_table('public.purchase_payments');
call private.secure_table('public.seller_payments');
call private.secure_table('public.vehicle_expenses');
call private.secure_table('public.supplier_payments');
call private.secure_table('public.reservations');
call private.secure_table('public.sales');
call private.secure_table('public.sale_payments');
call private.secure_table('public.customer_refunds');
-- Sale drafts (and their payment legs) may be deleted by the API (ERD §1).
grant delete on public.sales, public.sale_payments to app_api;

-- The API sees its tenant's rows; RLS for the browser follows the permission catalogue.
do $$
declare
  t text;
begin
  foreach t in array array[
    'customers', 'suppliers', 'locations', 'vehicles', 'vehicle_status_history', 'vehicle_location_history',
    'vehicle_price_history', 'vehicle_media', 'documents', 'vehicle_purchases', 'purchase_payments',
    'seller_payments', 'vehicle_expenses', 'supplier_payments', 'reservations', 'sales', 'sale_payments',
    'customer_refunds']
  loop
    execute format(
      'create policy %I on public.%I for all to app_api
         using (tenant_id = (select private.current_tenant_id()))
         with check (tenant_id = (select private.current_tenant_id()))',
      t || '_api', t);
  end loop;
end;
$$;

create policy customers_read on public.customers for select to authenticated
  using (tenant_id = any ((select private.tenants_with_permission('customer.view'))::uuid[]));
create policy suppliers_read on public.suppliers for select to authenticated
  using (tenant_id = any ((select private.tenants_with_permission('supplier.manage'))::uuid[]));
create policy locations_read on public.locations for select to authenticated
  using (tenant_id = any ((select private.my_tenant_ids())::uuid[]));

-- Base vehicle rows carry the minimum price: only users who may see it and the
-- cost read them directly; everyone else uses vehicles_catalog.
create policy vehicles_read on public.vehicles for select to authenticated
  using (tenant_id = any ((select private.tenants_with_permission('vehicle.view_cost'))::uuid[])
     and tenant_id = any ((select private.tenants_with_permission('vehicle.view_min_price'))::uuid[]));
create policy vehicle_status_history_read on public.vehicle_status_history for select to authenticated
  using (tenant_id = any ((select private.tenants_with_permission('vehicle.view'))::uuid[]));
create policy vehicle_location_history_read on public.vehicle_location_history for select to authenticated
  using (tenant_id = any ((select private.tenants_with_permission('vehicle.view'))::uuid[]));
create policy vehicle_price_history_read on public.vehicle_price_history for select to authenticated
  using (tenant_id = any ((select private.tenants_with_permission('vehicle.view_min_price'))::uuid[]));
create policy vehicle_media_read on public.vehicle_media for select to authenticated
  using (tenant_id = any ((select private.tenants_with_permission('vehicle.view'))::uuid[]));
create policy documents_read on public.documents for select to authenticated
  using (
    (sensitivity = 'NORMAL' or tenant_id = any ((select private.tenants_with_permission('vehicle.view_cost'))::uuid[]))
    and ((entity_type = 'VEHICLE' and tenant_id = any ((select private.tenants_with_permission('vehicle.view'))::uuid[]))
      or (entity_type = 'CUSTOMER' and tenant_id = any ((select private.tenants_with_permission('customer.view'))::uuid[]))
      or (entity_type = 'SALE' and tenant_id = any ((select private.tenants_with_permission('sale.view'))::uuid[]))
      or (entity_type = 'SUPPLIER' and tenant_id = any ((select private.tenants_with_permission('supplier.manage'))::uuid[])))
  );

create policy vehicle_purchases_read on public.vehicle_purchases for select to authenticated
  using (tenant_id = any ((select private.tenants_with_permission('vehicle.view_cost'))::uuid[]));
create policy purchase_payments_read on public.purchase_payments for select to authenticated
  using (tenant_id = any ((select private.tenants_with_permission('vehicle.view_cost'))::uuid[]));
create policy seller_payments_read on public.seller_payments for select to authenticated
  using (tenant_id = any ((select private.tenants_with_permission('vehicle.view_cost'))::uuid[]));
create policy vehicle_expenses_read on public.vehicle_expenses for select to authenticated
  using (tenant_id = any ((select private.tenants_with_permission('vehicle.view_cost'))::uuid[]));
create policy supplier_payments_read on public.supplier_payments for select to authenticated
  using (tenant_id = any ((select private.tenants_with_permission('supplier.manage'))::uuid[]));
create policy customer_refunds_read on public.customer_refunds for select to authenticated
  using (tenant_id = any ((select private.tenants_with_permission('cash.view'))::uuid[]));
create policy reservations_read on public.reservations for select to authenticated
  using (tenant_id = any ((select private.tenants_with_permission('sale.view'))::uuid[])
      or tenant_id = any ((select private.tenants_with_permission('reservation.manage'))::uuid[]));
-- Sales staff see posted sales and their own drafts (ARCHITECTURE §7).
create policy sales_read on public.sales for select to authenticated
  using (tenant_id = any ((select private.tenants_with_permission('sale.view'))::uuid[])
     and (status <> 'DRAFT' or created_by = (select auth.uid())
          or tenant_id = any ((select private.tenants_with_permission('sale.post'))::uuid[])));
create policy sale_payments_read on public.sale_payments for select to authenticated
  using (tenant_id = any ((select private.tenants_with_permission('sale.view'))::uuid[]));

-- -----------------------------------------------------------------------------
-- Storage (D-15): private buckets. Objects are uploaded and read only through
-- short-lived signed URLs issued by the API, so no storage policy grants the
-- browser direct access (D-74).
-- -----------------------------------------------------------------------------
insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values
  ('vehicle-media', 'vehicle-media', false, 5242880, array['image/webp', 'image/jpeg', 'image/png']),
  ('documents', 'documents', false, 10485760,
   array['application/pdf', 'image/webp', 'image/jpeg', 'image/png'])
on conflict (id) do nothing;

revoke execute on all routines in schema private from public, anon, authenticated, service_role;
grant execute on function
  private.current_tenant_id(), private.current_user_id(), private.current_actor_id(),
  private.my_tenant_ids(), private.tenants_with_permission(text), private.is_member(uuid),
  private.has_permission(uuid, text), private.has_any_permission(uuid, text[]),
  private.my_partner_id(uuid), private.is_platform_admin(), private.tenant_writable(uuid),
  private.feature_enabled(uuid, text)
  to authenticated, app_api;
