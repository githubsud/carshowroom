import { expect, test } from '@playwright/test';

import { AS_OWNER, AS_PARTNER, AS_SALES, DOHA, expectDirection, login, NOUR } from './helpers';

/**
 * Phase 1 acceptance (SPEC §13): a user logs in, sees only their tenant,
 * switches language with correct RTL, and the menu follows the role.
 */

test.describe('signing in', () => {
  test('owner logs in straight into their only showroom, in Arabic RTL', async ({ page }) => {
    await login(page, 'owner@nour.example');
    await expect(page).toHaveURL(new RegExp(`/t/${NOUR}/dashboard$`));
    await expect(page.getByTestId('dashboard-title')).toContainText('معرض النور للسيارات');
    await expect(page.getByTestId('role')).toContainText('المالك');
    await expectDirection(page, 'ar');
  });

  test('wrong password shows a translated error', async ({ page }) => {
    await login(page, 'owner@nour.example', 'Wrong-Pass-2026');
    await expect(page.getByTestId('login-error')).toContainText('البريد الإلكتروني أو كلمة السر غلط');
  });

  test('tenant pages require signing in', async ({ page }) => {
    await page.goto(`/t/${NOUR}/dashboard`);
    await expect(page).toHaveURL(/\/login\?returnUrl=/);
  });
});

test.describe('owner', () => {
  test.use({ storageState: AS_OWNER });

  test('sees every module in the menu', async ({ page }) => {
    await page.goto(`/t/${NOUR}/dashboard`);
    const sidebar = page.getByTestId('sidebar');
    for (const key of ['dashboard', 'vehicles', 'partners', 'finance', 'users', 'settings', 'audit']) {
      await expect(sidebar.getByTestId(`nav-${key}`)).toBeVisible();
    }
  });

  test('language switch flips the layout to English LTR and is remembered', async ({ page }) => {
    await page.goto(`/t/${NOUR}/dashboard`);
    await expect(page.getByTestId('dashboard-title')).toBeVisible();
    await expectDirection(page, 'ar');

    await page.getByTestId('language-toggle').locator('button').click();
    await expectDirection(page, 'en');
    await expect(page.getByTestId('dashboard-title')).toContainText('Welcome to Al Nour Motors');
    await expect(page.getByTestId('nav-dashboard')).toContainText('Dashboard');

    // The sidebar moves from the right edge (RTL) to the left edge (LTR).
    const ltrBox = await page.getByTestId('sidebar').boundingBox();
    expect(ltrBox?.x).toBeLessThan(10);

    await page.reload();
    await expectDirection(page, 'en');

    await page.getByTestId('language-toggle').locator('button').click();
    await expectDirection(page, 'ar');
    const rtlBox = await page.getByTestId('sidebar').boundingBox();
    const width = page.viewportSize()?.width ?? 0;
    expect((rtlBox?.x ?? 0) + (rtlBox?.width ?? 0)).toBeGreaterThan(width - 10);
  });

  test('cannot open a showroom they do not belong to by URL', async ({ page }) => {
    await page.goto(`/t/${DOHA}/dashboard`);
    // Bounced to the switcher, which forwards to the only allowed showroom.
    await expect(page).toHaveURL(new RegExp(`/t/${NOUR}/dashboard$`));
    await expect(page.getByTestId('active-tenant')).toContainText('معرض النور');
  });

  test('sees the showroom users', async ({ page }) => {
    await page.goto(`/t/${NOUR}/dashboard`);
    await page.getByTestId('nav-users').click();
    const table = page.getByTestId('users-table');
    await expect(table.locator('tbody tr')).toHaveCount(4);
    await expect(table).toContainText('accountant@nour.example');
  });

  test('sign out returns to login', async ({ page }) => {
    await page.goto(`/t/${NOUR}/dashboard`);
    await page.getByTestId('sign-out').locator('button').click();
    await expect(page).toHaveURL(/\/login$/);
    await page.goto(`/t/${NOUR}/dashboard`);
    await expect(page).toHaveURL(/\/login\?returnUrl=/);
  });
});

test.describe('partner in two showrooms', () => {
  test.use({ storageState: AS_PARTNER });

  test('chooses between them and sees only partner menus', async ({ page }) => {
    await page.goto('/tenants');
    await expect(page.getByTestId('tenant-list').getByRole('button')).toHaveCount(2);

    await page.getByTestId(`tenant-${DOHA}`).click();
    await expect(page).toHaveURL(new RegExp(`/t/${DOHA}/dashboard$`));
    await expect(page.getByTestId('active-tenant')).toContainText('معرض الدوحة');

    // Dashboard, partners and their own account security; nothing else.
    const items = page.getByTestId('sidebar').locator('a');
    await expect(items).toHaveCount(3);
    await expect(page.getByTestId('nav-partners')).toBeVisible();
    await expect(page.getByTestId('nav-account')).toBeVisible();

    // Switch back through the top bar.
    await page.getByTestId('active-tenant').click();
    await page.getByTestId(`tenant-${NOUR}`).click();
    await expect(page.getByTestId('active-tenant')).toContainText('معرض النور');
  });
});

test.describe('sales staff', () => {
  test.use({ storageState: AS_SALES });

  test('see no partner, finance or settings menus and cannot open them', async ({ page }) => {
    await page.goto(`/t/${NOUR}/dashboard`);
    const sidebar = page.getByTestId('sidebar');
    await expect(sidebar.getByTestId('nav-vehicles')).toBeVisible();
    for (const key of ['partners', 'finance', 'reports', 'users', 'settings', 'audit']) {
      await expect(sidebar.getByTestId(`nav-${key}`)).toHaveCount(0);
    }
    await page.goto(`/t/${NOUR}/settings/users`);
    await expect(page).toHaveURL(new RegExp(`/t/${NOUR}/dashboard$`));
  });
});
