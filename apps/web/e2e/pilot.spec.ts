import { expect, test } from '@playwright/test';

import { AS_OWNER, NOUR } from './helpers';

/**
 * Pilot accountant review through the UI: one direct expense split over two cars
 * (D-71 follow-up). The Yaris (cost 330,000) and the Rio share a 3,000 transport bill.
 */

test.use({ storageState: AS_OWNER });

const YARIS = 'e1000000-0000-0000-0000-000000000009';

test('one expense is split over two cars, each taking its part', async ({ page }) => {
  await page.goto(`/t/${NOUR}/vehicles/${YARIS}`);
  await expect(page.getByTestId('total-cost')).toContainText('330,000.00');

  await page.getByTestId('add-expense').locator('button').click();
  await page.getByTestId('expense-chips').getByText('نقل').click();
  await page.getByTestId('amount').locator('input').fill('3000');
  await page.getByTestId('expense-split').click();
  await page.getByTestId('expense-split-cars').click();
  await page.getByRole('option', { name: /V-2026-0008/ }).click();
  await page.keyboard.press('Escape');
  await expect(page.getByTestId(`share-${YARIS}`).locator('input')).toHaveValue(/1,?500/);

  await page.getByTestId('review').locator('button').click();
  await expect(page.getByTestId('preview-summary')).toContainText('موزع على 2 سيارات');
  await page.getByTestId('confirm').locator('button').click();
  await expect(page.getByTestId('total-cost')).toContainText('331,500.00');
});
