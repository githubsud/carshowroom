import { expect, test } from '@playwright/test';

import { AS_OWNER, NOUR } from './helpers';

test.use({ storageState: AS_OWNER });

/** Mobile-first shell (SPEC §9.1): bottom bar, drawer menu, no horizontal scroll. */
test('owner on a phone navigates with the bottom bar and the drawer', async ({ page }) => {
  await page.goto(`/t/${NOUR}/dashboard`);
  await expect(page.getByTestId('dashboard-title')).toBeVisible();
  await expect(page.getByTestId('sidebar')).toBeHidden();

  const scrollWidth = await page.evaluate(() => document.documentElement.scrollWidth);
  const viewportWidth = page.viewportSize()?.width ?? 0;
  expect(scrollWidth).toBeLessThanOrEqual(viewportWidth);

  // The dashboard's blocks load after the first paint; they must not widen the page either.
  await page.getByTestId('kpi-tiles').waitFor();
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(viewportWidth);
  await page.getByRole('button', { name: 'المزيد' }).click();
  await page.getByTestId('drawer-nav').getByRole('link', { name: 'المستخدمين' }).click();
  await expect(page).toHaveURL(new RegExp(`/t/${NOUR}/settings/users$`));
});

/** BACKLOG 4.7: a vehicle expense on a phone takes under 15 seconds. */
test('records a vehicle expense on a phone in under 15 seconds', async ({ page }) => {
  await page.goto(`/t/${NOUR}/vehicles/e1000000-0000-0000-0000-000000000002`);
  await expect(page.getByTestId('add-expense')).toBeVisible();

  const started = Date.now();
  await page.getByTestId('add-expense').locator('button').click();
  await page.getByTestId('expense-chips').getByText('نقل').click();
  await page.getByTestId('amount').locator('input').fill('750');
  await page.getByTestId('review').locator('button').click();
  await page.getByTestId('confirm').locator('button').click();
  await expect(page.getByText(/تم التسجيل — قيد رقم \d+/)).toBeVisible();
  expect(Date.now() - started).toBeLessThan(15_000);
});

/** BACKLOG 6.4: a call is logged in at most three taps on a phone. */
test('logs a call in three taps or fewer', async ({ page }) => {
  await page.goto(`/t/${NOUR}/customers/d0000000-0000-0000-0000-000000000003`);
  const crm = page.getByTestId('customer-crm');
  await expect(crm).toBeVisible();

  let taps = 0;
  await crm.getByTestId('log-call-customer').locator('button').click();
  taps += 1;
  await crm.getByTestId('call-ANSWERED').locator('button').click();
  taps += 1;
  await expect(page.getByText('تم تسجيل المكالمة')).toBeVisible();
  await expect(page.getByTestId('customer-follow-ups')).toContainText('رد');
  expect(taps).toBeLessThanOrEqual(3);
});
