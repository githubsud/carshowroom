import { Routes } from '@angular/router';

import { authGuard, guestGuard, permissionGuard, tenantGuard } from './core/auth/guards';

export const routes: Routes = [
  { path: '', pathMatch: 'full', redirectTo: 'tenants' },
  {
    path: 'login',
    canActivate: [guestGuard],
    loadComponent: () => import('./features/auth/login.page').then((m) => m.LoginPage),
  },
  {
    path: 'forgot-password',
    canActivate: [guestGuard],
    loadComponent: () => import('./features/auth/forgot-password.page').then((m) => m.ForgotPasswordPage),
  },
  {
    // Invitation and recovery links land here; no guard (the session arrives in the URL).
    path: 'reset-password',
    loadComponent: () => import('./features/auth/reset-password.page').then((m) => m.ResetPasswordPage),
  },
  {
    path: 'tenants',
    canActivate: [authGuard],
    loadComponent: () => import('./features/tenants/tenant-switcher.page').then((m) => m.TenantSwitcherPage),
  },
  {
    // Tenant id in the URL (D-32): deep links open the right showroom.
    path: 't/:tenantId',
    canActivate: [authGuard, tenantGuard],
    loadComponent: () => import('./core/layout/shell.component').then((m) => m.ShellComponent),
    children: [
      { path: '', pathMatch: 'full', redirectTo: 'dashboard' },
      {
        path: 'dashboard',
        loadComponent: () => import('./features/dashboard/dashboard.page').then((m) => m.DashboardPage),
      },
      {
        path: 'settings/users',
        canActivate: [permissionGuard('users.manage')],
        loadComponent: () => import('./features/settings/users/users.page').then((m) => m.UsersPage),
      },
      {
        path: 'finance/cash',
        canActivate: [permissionGuard('cash.view')],
        loadComponent: () => import('./features/finance/cash.page').then((m) => m.CashPage),
      },
      {
        path: 'finance/journal',
        canActivate: [permissionGuard('journal.view')],
        loadComponent: () => import('./features/finance/journal.page').then((m) => m.JournalPage),
      },
      {
        path: 'finance/periods',
        canActivate: [permissionGuard('period.lock', 'journal.view')],
        loadComponent: () => import('./features/finance/periods.page').then((m) => m.PeriodsPage),
      },
      {
        path: 'settings/finance',
        canActivate: [permissionGuard('tenant.settings.manage')],
        loadComponent: () => import('./features/settings/finance/finance-settings.page').then((m) => m.FinanceSettingsPage),
      },
      {
        path: 'partners',
        canActivate: [permissionGuard('partner.view_all', 'partner.view_own')],
        loadComponent: () => import('./features/partners/partners.page').then((m) => m.PartnersPage),
      },
      {
        path: 'partners/:partnerId',
        canActivate: [permissionGuard('partner.view_all', 'partner.view_own')],
        loadComponent: () => import('./features/partners/partner-statement.page').then((m) => m.PartnerStatementPage),
      },
      {
        path: 'vehicles',
        canActivate: [permissionGuard('vehicle.view')],
        loadComponent: () => import('./features/vehicles/inventory.page').then((m) => m.InventoryPage),
      },
      {
        path: 'vehicles/:vehicleId',
        canActivate: [permissionGuard('vehicle.view')],
        loadComponent: () => import('./features/vehicles/vehicle-file.page').then((m) => m.VehicleFilePage),
      },
      {
        path: 'customers',
        canActivate: [permissionGuard('customer.view')],
        loadComponent: () => import('./features/customers/customers.page').then((m) => m.CustomersPage),
      },
      {
        path: 'customers/:customerId',
        canActivate: [permissionGuard('customer.view')],
        loadComponent: () => import('./features/customers/customer.page').then((m) => m.CustomerPage),
      },
      {
        path: 'suppliers',
        canActivate: [permissionGuard('supplier.manage')],
        loadComponent: () => import('./features/suppliers/suppliers.page').then((m) => m.SuppliersPage),
      },
      {
        path: 'sales',
        canActivate: [permissionGuard('sale.view')],
        loadComponent: () => import('./features/sales/sales.page').then((m) => m.SalesPage),
      },
      {
        path: 'sales/new',
        canActivate: [permissionGuard('sale.draft')],
        loadComponent: () => import('./features/sales/sale.page').then((m) => m.SalePage),
      },
      {
        path: 'sales/:saleId',
        canActivate: [permissionGuard('sale.view')],
        loadComponent: () => import('./features/sales/sale.page').then((m) => m.SalePage),
      },
      {
        path: 'installments',
        canActivate: [permissionGuard('installment.view')],
        loadComponent: () => import('./features/installments/installments.page').then((m) => m.InstallmentsPage),
      },
      {
        path: 'installments/plans/:planId',
        canActivate: [permissionGuard('installment.view')],
        loadComponent: () => import('./features/installments/plan.page').then((m) => m.PlanPage),
      },
      {
        path: 'installments/papers',
        canActivate: [permissionGuard('deferred_paper.manage')],
        loadComponent: () => import('./features/installments/papers.page').then((m) => m.PapersPage),
      },
      {
        path: 'consignments',
        canActivate: [permissionGuard('consignment.manage')],
        loadComponent: () => import('./features/consignment/consignments.page').then((m) => m.ConsignmentsPage),
      },
      {
        path: 'consignments/showrooms/:showroomId',
        canActivate: [permissionGuard('consignment.settle')],
        loadComponent: () => import('./features/consignment/showroom.page').then((m) => m.ShowroomPage),
      },
      {
        path: 'consignments/:consignmentId',
        canActivate: [permissionGuard('consignment.manage')],
        loadComponent: () => import('./features/consignment/consignment.page').then((m) => m.ConsignmentPage),
      },
      {
        path: 'requests',
        canActivate: [permissionGuard('customer.view')],
        loadComponent: () => import('./features/requests/requests.page').then((m) => m.RequestsPage),
      },
      {
        path: 'reports',
        canActivate: [permissionGuard('report.financial', 'journal.view', 'vehicle.view_cost')],
        loadComponent: () => import('./features/reports/reports.page').then((m) => m.ReportsPage),
      },
      {
        path: 'distribution',
        canActivate: [permissionGuard('profit.distribute', 'partner.view_all')],
        loadComponent: () => import('./features/reports/distribution.page').then((m) => m.DistributionPage),
      },
      {
        path: 'settings/policies',
        canActivate: [permissionGuard('tenant.settings.manage')],
        loadComponent: () => import('./features/settings/policies.page').then((m) => m.PoliciesPage),
      },
      {
        path: 'notifications',
        loadComponent: () => import('./features/misc/notifications.page').then((m) => m.NotificationsPage),
      },
      {
        path: 'soon/:feature',
        loadComponent: () => import('./features/misc/coming-soon.page').then((m) => m.ComingSoonPage),
      },
    ],
  },
  {
    path: '**',
    loadComponent: () => import('./features/misc/not-found.page').then((m) => m.NotFoundPage),
  },
];
