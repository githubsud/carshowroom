-- =============================================================================
-- Reference data needed in every environment: country packs, the permission
-- catalogue, system role bundles (ARCHITECTURE §7, approved 2026-10-02 as Q-05
-- with restrictive defaults), plans and plan feature flags.
-- =============================================================================

insert into public.country_packs
  (code, name_ar, name_en, currency_code, default_timezone, default_language, default_digit_style, arabic_locale, einvoice_adapter)
values
  ('EG', 'مصر', 'Egypt', 'EGP', 'Africa/Cairo', 'ar', 'WESTERN', 'ar-EG', 'egypt_eta_stub'),
  ('QA', 'قطر', 'Qatar', 'QAR', 'Asia/Qatar', 'ar', 'WESTERN', 'ar-QA', 'none');

-- -----------------------------------------------------------------------------
-- Permission catalogue. Keep in sync with apps/api/app/domain/permissions.py
-- (a test compares the two).
-- -----------------------------------------------------------------------------
insert into public.permissions (code, scope, description) values
  ('tenant.settings.manage',  'TENANT',   'Change showroom profile and settings'),
  ('users.manage',            'TENANT',   'Invite users and change their roles'),
  ('support.grant',           'TENANT',   'Grant time-boxed support access to the platform'),
  ('dashboard.view',          'TENANT',   'See the operational dashboard'),
  ('dashboard.financial',     'TENANT',   'See cash, bank and partner blocks on the dashboard'),
  ('vehicle.view',            'TENANT',   'See vehicles (no cost data)'),
  ('vehicle.manage',          'TENANT',   'Edit vehicle master data, moves and media'),
  ('vehicle.view_cost',       'TENANT',   'See purchase price, expenses, total cost and profit'),
  ('vehicle.view_min_price',  'TENANT',   'See the minimum acceptable price'),
  ('vehicle.purchase',        'TENANT',   'Record vehicle purchases'),
  ('vehicle.expense.record',  'TENANT',   'Record vehicle expenses'),
  ('customer.view',           'TENANT',   'See customers'),
  ('customer.manage',         'TENANT',   'Create and edit customers'),
  ('customer.view_national_id','TENANT',  'See unmasked national IDs (audit-logged)'),
  ('request.manage',          'TENANT',   'Manage customer car requests and matches'),
  ('followup.manage',         'TENANT',   'Log calls and follow-ups'),
  ('sale.view',               'TENANT',   'See sales'),
  ('sale.draft',              'TENANT',   'Create and edit sale drafts'),
  ('sale.post',               'TENANT',   'Confirm and post sales'),
  ('sale.cancel',             'TENANT',   'Cancel posted sales'),
  ('reservation.manage',      'TENANT',   'Take, refund or forfeit deposits'),
  ('installment.view',        'TENANT',   'See installments and the due list'),
  ('installment.collect',     'TENANT',   'Record installment payments'),
  ('deferred_paper.manage',   'TENANT',   'Manage promissory notes and post-dated cheques'),
  ('consignment.manage',      'TENANT',   'Manage consignment agreements and moves'),
  ('consignment.settle',      'TENANT',   'Settle consignors and collect from external showrooms'),
  ('partner.view_all',        'TENANT',   'See all partners and their statements'),
  ('partner.view_own',        'TENANT',   'See own partner statement'),
  ('partner.transact',        'TENANT',   'Record partner contributions, drawings and loans'),
  ('partner.equity.change',   'TENANT',   'Change partners and ownership percentages'),
  ('cash.view',               'TENANT',   'See cash and bank balances and books'),
  ('cash.transact',           'TENANT',   'Record transfers, general expenses and other income'),
  ('supplier.manage',         'TENANT',   'Manage suppliers'),
  ('supplier.pay',            'TENANT',   'Pay suppliers'),
  ('journal.view',            'TENANT',   'See journal entries, general ledger and trial balance'),
  ('journal.reverse',         'TENANT',   'Reverse posted entries'),
  ('period.lock',             'TENANT',   'Lock accounting months'),
  ('period.unlock',           'TENANT',   'Unlock accounting months'),
  ('profit.distribute',       'TENANT',   'Close periods and distribute profit'),
  ('report.financial',        'TENANT',   'Run financial reports'),
  ('import.run',              'TENANT',   'Run Excel imports'),
  ('audit.view',              'TENANT',   'See the audit log'),
  ('platform.tenants.manage', 'PLATFORM', 'Manage tenants, plans and flags'),
  ('platform.billing.manage', 'PLATFORM', 'Manage subscriptions and manual invoices'),
  ('platform.support.access', 'PLATFORM', 'Open support sessions with a tenant grant');

-- Hard limits that no tenant configuration can lift (SPEC §1.2, §10).
insert into public.role_permission_restrictions (role_code, permission_code, reason) values
  ('SALES', 'vehicle.view_cost',      'SPEC §1.2/§10: sales never sees cost or profit'),
  ('SALES', 'vehicle.view_min_price', 'SPEC §1.2/§10: sales never sees the minimum price'),
  ('SALES', 'partner.view_all',       'SPEC §1.2: sales has no access to partner accounts'),
  ('SALES', 'partner.transact',       'SPEC §1.2: sales has no access to partner accounts'),
  ('SALES', 'journal.view',           'Ledger lines expose cost'),
  ('SALES', 'report.financial',       'Financial reports expose cost and profit'),
  ('MANAGER', 'partner.equity.change','SPEC §1.2: manager cannot change partner equity'),
  ('MANAGER', 'period.unlock',        'SPEC §1.2: manager cannot unlock periods'),
  ('MANAGER', 'tenant.settings.manage','SPEC §1.2: manager cannot change settings'),
  ('ACCOUNTANT', 'tenant.settings.manage','SPEC §1.2: accountant cannot change settings'),
  ('PARTNER', 'partner.view_all',     'SPEC §1.2: partner sees only own statement'),
  ('VIEWER', 'vehicle.view_cost',     'Q-05 restrictive default (owner may revisit)');

-- -----------------------------------------------------------------------------
-- System roles.
-- -----------------------------------------------------------------------------
insert into public.roles (code, name_ar, name_en, is_system, sort_order) values
  ('OWNER',      'المالك / الشريك المدير', 'Owner / Managing partner', true, 1),
  ('MANAGER',    'مدير المعرض',            'Manager',                  true, 2),
  ('ACCOUNTANT', 'المحاسب',                'Accountant',               true, 3),
  ('SALES',      'موظف المبيعات',          'Sales staff',              true, 4),
  ('PARTNER',    'شريك',                   'Partner',                  true, 5),
  ('VIEWER',     'مشاهد',                  'Viewer',                   true, 6);

-- Owner: every tenant permission.
insert into public.role_permissions (role_id, permission_code)
select r.id, p.code
from public.roles r
cross join public.permissions p
where r.code = 'OWNER' and r.tenant_id is null and p.scope = 'TENANT';

insert into public.role_permissions (role_id, permission_code)
select r.id, x.code
from public.roles r
join (values
  -- Manager: operations and finance; sale.post only through a tenant override.
  ('MANAGER', 'dashboard.view'), ('MANAGER', 'dashboard.financial'),
  ('MANAGER', 'vehicle.view'), ('MANAGER', 'vehicle.manage'), ('MANAGER', 'vehicle.view_cost'),
  ('MANAGER', 'vehicle.purchase'), ('MANAGER', 'vehicle.expense.record'),
  ('MANAGER', 'customer.view'), ('MANAGER', 'customer.manage'), ('MANAGER', 'customer.view_national_id'),
  ('MANAGER', 'request.manage'), ('MANAGER', 'followup.manage'),
  ('MANAGER', 'sale.view'), ('MANAGER', 'sale.draft'), ('MANAGER', 'reservation.manage'),
  ('MANAGER', 'installment.view'), ('MANAGER', 'installment.collect'), ('MANAGER', 'deferred_paper.manage'),
  ('MANAGER', 'consignment.manage'), ('MANAGER', 'consignment.settle'),
  ('MANAGER', 'partner.view_all'), ('MANAGER', 'partner.transact'),
  ('MANAGER', 'cash.view'), ('MANAGER', 'cash.transact'),
  ('MANAGER', 'supplier.manage'), ('MANAGER', 'supplier.pay'),
  ('MANAGER', 'report.financial'),
  -- Accountant: all financial recording, reversal and reports; no settings,
  -- users, equity changes, period lock/unlock or distribution.
  ('ACCOUNTANT', 'dashboard.view'), ('ACCOUNTANT', 'dashboard.financial'),
  ('ACCOUNTANT', 'vehicle.view'), ('ACCOUNTANT', 'vehicle.manage'), ('ACCOUNTANT', 'vehicle.view_cost'),
  ('ACCOUNTANT', 'vehicle.view_min_price'), ('ACCOUNTANT', 'vehicle.purchase'), ('ACCOUNTANT', 'vehicle.expense.record'),
  ('ACCOUNTANT', 'customer.view'), ('ACCOUNTANT', 'customer.manage'), ('ACCOUNTANT', 'customer.view_national_id'),
  ('ACCOUNTANT', 'request.manage'), ('ACCOUNTANT', 'followup.manage'),
  ('ACCOUNTANT', 'sale.view'), ('ACCOUNTANT', 'sale.draft'), ('ACCOUNTANT', 'sale.post'), ('ACCOUNTANT', 'sale.cancel'),
  ('ACCOUNTANT', 'reservation.manage'),
  ('ACCOUNTANT', 'installment.view'), ('ACCOUNTANT', 'installment.collect'), ('ACCOUNTANT', 'deferred_paper.manage'),
  ('ACCOUNTANT', 'consignment.manage'), ('ACCOUNTANT', 'consignment.settle'),
  ('ACCOUNTANT', 'partner.view_all'), ('ACCOUNTANT', 'partner.transact'),
  ('ACCOUNTANT', 'cash.view'), ('ACCOUNTANT', 'cash.transact'),
  ('ACCOUNTANT', 'supplier.manage'), ('ACCOUNTANT', 'supplier.pay'),
  ('ACCOUNTANT', 'journal.view'), ('ACCOUNTANT', 'journal.reverse'),
  ('ACCOUNTANT', 'report.financial'), ('ACCOUNTANT', 'import.run'), ('ACCOUNTANT', 'audit.view'),
  -- Sales: vehicles (no cost), customers, requests, drafts, read-only due list.
  ('SALES', 'dashboard.view'),
  ('SALES', 'vehicle.view'), ('SALES', 'vehicle.manage'),
  ('SALES', 'customer.view'), ('SALES', 'customer.manage'),
  ('SALES', 'request.manage'), ('SALES', 'followup.manage'),
  ('SALES', 'sale.view'), ('SALES', 'sale.draft'),
  ('SALES', 'installment.view'),
  ('SALES', 'consignment.manage'),
  -- Partner: own statement only (summary through tenant_settings.partner_sees_summary).
  ('PARTNER', 'partner.view_own'),
  -- Viewer: read-only operational view, no cost data.
  ('VIEWER', 'dashboard.view'), ('VIEWER', 'vehicle.view'), ('VIEWER', 'customer.view'),
  ('VIEWER', 'sale.view'), ('VIEWER', 'installment.view')
) as x (role_code, code) on x.role_code = r.code
where r.tenant_id is null;

-- -----------------------------------------------------------------------------
-- Plans and plan-level feature flags (SPEC §4.16). Limits are enforced from
-- Phase 9; values here are placeholders for the product owner to set.
-- -----------------------------------------------------------------------------
insert into public.plans (code, name_ar, name_en, limits) values
  ('TRIAL',    'تجريبي', 'Trial',    '{"users": 5, "branches": 1, "vehicles_in_stock": 50}'),
  ('STANDARD', 'أساسي',  'Standard', '{"users": 15, "branches": 3, "vehicles_in_stock": 500}');

insert into public.feature_flags (plan_id, flag_key, enabled)
select p.id, f.flag_key, f.enabled
from public.plans p
cross join (values
  ('installments', true),
  ('consignment', true),
  ('multi_branch', false),
  ('car_level_investors', false)
) as f (flag_key, enabled);

update public.feature_flags f
set enabled = true
from public.plans p
where f.plan_id = p.id and p.code = 'STANDARD' and f.flag_key = 'multi_branch';
