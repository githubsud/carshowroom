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

test('an installment sale carries the markup the owner sets', async ({ page }) => {
  test.setTimeout(120_000);
  // Turned on in Settings → Policies (Q-03, docs/SHARIA.md).
  await page.goto(`/t/${NOUR}/settings/policies`);
  await page.locator('#pol-installment_markup_mode').click();
  await page.getByRole('option', { name: 'بثمن تقسيط يحدده المعرض في كل بيعة' }).click();
  await page.getByTestId('policies-save').locator('button').click();
  await expect(page.getByText('تم الحفظ').first()).toBeVisible();

  // Nissan Sentra, asking 585,000: 85,000 down, the 500,000 left plus 10% over 5 months.
  await page.goto(`/t/${NOUR}/vehicles/e1000000-0000-0000-0000-000000000010`);
  await page.getByTestId('sell').locator('button').click();
  await page.getByTestId('buyer-picker').locator('input').fill('حسن');
  await page.getByRole('option', { name: /حسن علي/ }).click();
  await page.getByTestId('payment-amount-0').locator('input').fill('85000');
  await page.getByTestId('use-installments').click();
  await page.getByTestId('inst-count').fill('5');
  await page.getByTestId('inst-markup-pct').fill('10');
  await page.getByTestId('inst-markup-pct').press('Tab');
  await expect(page.getByTestId('financed')).toContainText('500,000.00');
  await expect(page.getByTestId('installments-total')).toContainText('550,000.00');
  await expect(page.getByTestId('schedule-preview').locator('li')).toHaveCount(5);
  await expect(page.getByTestId('schedule-preview')).toContainText('110,000.00');

  await page.getByTestId('post-sale').locator('button').click();
  await expect(page.getByTestId('preview-summary')).toContainText('فرق سعر التقسيط');
  await page.getByTestId('confirm').locator('button').click();
  await expect(page.getByTestId('sale-status')).toContainText('مرحّل');
});
