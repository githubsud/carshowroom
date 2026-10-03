/**
 * Main navigation. Items are shown by permission and feature flag
 * (SPEC §9.1). Modules not built yet route to a "coming soon" page so the menu
 * already reflects each role.
 */
export interface MenuItem {
  key: string;
  icon: string;
  path: string;
  anyOf: readonly string[];
  flag?: string;
  /** Shown in the mobile bottom bar. */
  primary?: boolean;
}

export const MENU: readonly MenuItem[] = [
  { key: 'dashboard', icon: 'pi pi-home', path: 'dashboard', anyOf: ['dashboard.view', 'partner.view_own'], primary: true },
  { key: 'vehicles', icon: 'pi pi-car', path: 'vehicles', anyOf: ['vehicle.view'], primary: true },
  { key: 'customers', icon: 'pi pi-users', path: 'customers', anyOf: ['customer.view'] },
  { key: 'requests', icon: 'pi pi-phone', path: 'requests', anyOf: ['customer.view'] },
  { key: 'sales', icon: 'pi pi-shopping-cart', path: 'sales', anyOf: ['sale.view'] },
  {
    key: 'installments',
    icon: 'pi pi-calendar',
    path: 'installments',
    anyOf: ['installment.view'],
    flag: 'installments',
    primary: true,
  },
  {
    key: 'consignments',
    icon: 'pi pi-arrow-right-arrow-left',
    path: 'consignments',
    anyOf: ['consignment.manage'],
    flag: 'consignment',
  },
  { key: 'suppliers', icon: 'pi pi-wrench', path: 'suppliers', anyOf: ['supplier.manage'] },
  { key: 'partners', icon: 'pi pi-briefcase', path: 'partners', anyOf: ['partner.view_all', 'partner.view_own'] },
  { key: 'finance', icon: 'pi pi-wallet', path: 'finance/cash', anyOf: ['cash.view'] },
  { key: 'journal', icon: 'pi pi-book', path: 'finance/journal', anyOf: ['journal.view'] },
  { key: 'periods', icon: 'pi pi-calendar-times', path: 'finance/periods', anyOf: ['period.lock', 'journal.view'] },
  { key: 'reports', icon: 'pi pi-chart-bar', path: 'soon/reports', anyOf: ['report.financial'] },
  { key: 'users', icon: 'pi pi-user-plus', path: 'settings/users', anyOf: ['users.manage'] },
  { key: 'settings', icon: 'pi pi-cog', path: 'settings/finance', anyOf: ['tenant.settings.manage'] },
  { key: 'audit', icon: 'pi pi-history', path: 'soon/audit', anyOf: ['audit.view'] },
];

export function visibleMenu(
  permissions: ReadonlySet<string>,
  flags: Readonly<Record<string, boolean>>,
  menu: readonly MenuItem[] = MENU,
): MenuItem[] {
  return menu.filter(
    (item) => item.anyOf.some((p) => permissions.has(p)) && (item.flag === undefined || flags[item.flag] === true),
  );
}
