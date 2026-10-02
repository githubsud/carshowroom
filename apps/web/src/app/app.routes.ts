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
