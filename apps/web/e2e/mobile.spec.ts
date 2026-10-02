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

  await page.getByRole('button', { name: 'المزيد' }).click();
  await page.getByTestId('drawer-nav').getByRole('link', { name: 'المستخدمين' }).click();
  await expect(page).toHaveURL(new RegExp(`/t/${NOUR}/settings/users$`));
});
