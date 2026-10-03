import { expect, test } from '@playwright/test';

import { AS_OWNER, login, NOUR } from './helpers';

/**
 * Phase 9 through the UI: self-serve signup to a new showroom; the platform
 * console sees a showroom only inside a support window the owner granted and
 * can suspend a showroom; offline the app says so and refuses writes; the
 * audit viewer shows before/after of a change.
 */

test.describe('as the owner', () => {
  test.use({ storageState: AS_OWNER });

  test('subscription shows usage; support access is granted and revoked', async ({ page }) => {
    await page.goto(`/t/${NOUR}/settings/subscription`);
    await expect(page.getByTestId('usage')).toContainText('TRIAL');
    await page.getByTestId('grant-reason').fill('E2E: checking a report');
    await page.getByTestId('grant-support').locator('button').click();
    const grants = page.getByTestId('grants');
    await expect(grants).toContainText('E2E: checking a report');
    await expect(grants.getByTestId('revoke-support').first()).toBeVisible();
    await grants.getByTestId('revoke-support').first().locator('button').click();
    await expect(grants.getByTestId('revoke-support')).toHaveCount(0);
  });

  test('the audit viewer opens a change with its before and after', async ({ page }) => {
    await page.goto(`/t/${NOUR}/audit`);
    await page.getByTestId('audit-entity').fill('vehicles');
    await page.getByTestId('audit-search').locator('button').click();
    const first = page.getByTestId('audit-list').locator('li button.head').first();
    await expect(first).toContainText('vehicles');
    await first.click();
    await expect(page.getByTestId('audit-diff')).toBeVisible();
  });

  test('offline the app shows a banner and refuses to record', async ({ page, context }) => {
    await page.goto(`/t/${NOUR}/settings/subscription`);
    await expect(page.getByTestId('usage')).toBeVisible();
    await context.setOffline(true);
    await expect(page.getByTestId('offline-banner')).toBeVisible();
    await page.getByTestId('branch-name').fill('فرع لا يُسجل');
    await page.getByTestId('branch-add').locator('button').click();
    await expect(page.getByText('أنت غير متصل؛ لا يمكن التسجيل الآن')).toBeVisible();
    await context.setOffline(false);
    await expect(page.getByTestId('offline-banner')).toHaveCount(0);
  });
});

test('signup to a new showroom; the platform console suspends it', async ({ browser }) => {
  test.setTimeout(150_000);
  const stamp = Date.now().toString().slice(-8);
  const email = `e2e-${stamp}@signup.example`;
  const showroom = `معرض تجربة ${stamp}`;

  const owner = await browser.newPage();
  await owner.goto('/login');
  await owner.getByTestId('signup-link').click();
  await owner.getByTestId('su-name').fill('مالك تجربة');
  await owner.getByTestId('su-email').fill(email);
  await owner.locator('#su-password').fill('Signup-Pass-2026');
  await owner.getByTestId('signup-submit').locator('button').click();
  await expect(owner).toHaveURL(/\/create-showroom$/);
  await owner.getByTestId('cs-name').fill(showroom);
  await owner.getByTestId('cs-create').locator('button').click();
  await expect(owner).toHaveURL(/\/t\/[^/]+\/onboarding$/);
  const tenantId = /\/t\/([^/]+)\//.exec(owner.url())![1];
  await owner.close();

  const admin = await browser.newPage();
  await login(admin, 'admin@sayyara.example');
  await expect(admin).toHaveURL(/\/tenants$/);
  await admin.getByTestId('admin-console').click();
  const row = admin.getByTestId(`admin-row-${tenantId}`);
  await expect(row).toContainText(showroom);
  await expect(row).toContainText('TRIAL');

  // No support window: the console cannot look inside.
  await admin.getByTestId(`admin-manage-${tenantId}`).locator('button').click();
  await admin.getByTestId('admin-support').locator('button').click();
  await expect(admin.getByTestId('admin-error')).toBeVisible();
  await expect(admin.getByTestId('admin-summary')).toHaveCount(0);

  await admin.getByTestId('admin-status').selectOption('SUSPENDED');
  await admin.getByTestId('admin-reason').fill('E2E: unpaid trial');
  await admin.getByTestId('admin-save').locator('button').click();
  await expect(row).toContainText('SUSPENDED');
  await admin.close();
});
