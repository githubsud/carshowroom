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
  { key: 'vehicles', icon: 'pi pi-car', path: 'soon/vehicles', anyOf: ['vehicle.view'], primary: true },
  { key: 'customers', icon: 'pi pi-users', path: 'soon/customers', anyOf: ['customer.view'] },
  { key: 'sales', icon: 'pi pi-shopping-cart', path: 'soon/sales', anyOf: ['sale.view'] },
  {
    key: 'installments',
    icon: 'pi pi-calendar',
    path: 'soon/installments',
    anyOf: ['installment.view'],
    flag: 'installments',
    primary: true,
  },
  {
    key: 'consignments',
    icon: 'pi pi-arrow-right-arrow-left',
    path: 'soon/consignments',
    anyOf: ['consignment.manage'],
    flag: 'consignment',
  },
  { key: 'partners', icon: 'pi pi-briefcase', path: 'soon/partners', anyOf: ['partner.view_all', 'partner.view_own'] },
  { key: 'finance', icon: 'pi pi-wallet', path: 'soon/finance', anyOf: ['cash.view'] },
  { key: 'reports', icon: 'pi pi-chart-bar', path: 'soon/reports', anyOf: ['report.financial'] },
  { key: 'users', icon: 'pi pi-user-plus', path: 'settings/users', anyOf: ['users.manage'] },
  { key: 'settings', icon: 'pi pi-cog', path: 'soon/settings', anyOf: ['tenant.settings.manage'] },
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
