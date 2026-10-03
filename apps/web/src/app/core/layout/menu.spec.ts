import { describe, expect, it } from 'vitest';

import { MENU, visibleMenu } from './menu';

const keys = (permissions: string[], flags: Record<string, boolean> = { installments: true, consignment: true }) =>
  visibleMenu(new Set(permissions), flags).map((item) => item.key);

// Bundles as seeded in supabase/migrations/*_reference_data.sql (only the parts the menu reads).
const SALES = [
  'dashboard.view',
  'vehicle.view',
  'vehicle.manage',
  'customer.view',
  'customer.manage',
  'request.manage',
  'followup.manage',
  'sale.view',
  'sale.draft',
  'installment.view',
  'consignment.manage',
];

describe('visibleMenu', () => {
  it('shows the owner everything', () => {
    const all = [...new Set(MENU.flatMap((item) => item.anyOf))];
    expect(keys(all)).toEqual(MENU.map((item) => item.key));
  });

  it('never shows partners, finance, reports or settings to sales staff', () => {
    const visible = keys(SALES);
    expect(visible).toContain('vehicles');
    expect(visible).not.toContain('partners');
    expect(visible).not.toContain('finance');
    expect(visible).not.toContain('reports');
    expect(visible).not.toContain('users');
    expect(visible).not.toContain('settings');
  });

  it('shows a partner only the dashboard, partners and their account', () => {
    expect(keys(['partner.view_own'])).toEqual(['dashboard', 'partners', 'account']);
  });

  it('hides modules switched off by a feature flag', () => {
    expect(keys(SALES, { installments: false, consignment: true })).not.toContain('installments');
    expect(keys(SALES, {})).not.toContain('consignments');
  });

  it('shows nothing without permissions', () => {
    expect(keys([])).toEqual([]);
  });
});
