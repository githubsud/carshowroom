import { expect, Page, test } from '@playwright/test';

import { AS_OWNER, NOUR } from './helpers';

/**
 * Phase 6 through the UI: a customer request matched when a car becomes
 * AVAILABLE (BACKLOG 6.6), and a consigned car received, sold (rule 16) and
 * settled with its owner (rule 17).
 */

async function money(page: Page, testId: string, value: string): Promise<void> {
  await page.getByTestId(testId).locator('input').fill(value);
}

async function pick(page: Page, testId: string, query: string, option: RegExp): Promise<void> {
  await page.getByTestId(testId).locator('input').fill(query);
  await page.getByRole('option', { name: option }).click();
}

test.use({ storageState: AS_OWNER });

test('a car that becomes available is matched to a waiting customer', async ({ page }) => {
  test.setTimeout(180_000);
  const make = `Haval${Date.now().toString(36)}`;

  await page.goto(`/t/${NOUR}/requests`);
  await page.getByTestId('add-request').locator('button').click();
  await pick(page, 'rq-customer', 'كريم', /كريم محمود/);
  await page.getByTestId('rq-make').fill(make);
  await page.getByTestId('rq-model').fill('Jolion');
  await money(page, 'rq-budget', '900000');
  await page.getByTestId('rq-save').locator('button').click();
  await expect(page.getByText('تم حفظ الطلب — 0 سيارة مناسبة الآن')).toBeVisible();

  // A matching car arrives and is put on sale.
  await page.goto(`/t/${NOUR}/vehicles`);
  await page.getByTestId('add-vehicle').locator('button').click();
  await page.getByTestId('vehicle-make').fill(make);
  await page.getByTestId('vehicle-model').fill('Jolion');
  await page.getByTestId('vehicle-year').fill('2023');
  await money(page, 'asking-price', '850000');
  await page.getByTestId('vehicle-save').locator('button').click();
  await pick(page, 'seller-picker', 'كريم', /كريم محمود/);
  await money(page, 'purchase-price', '700000');
  await money(page, 'paid-now', '700000');
  await page.getByText('جاهزة للبيع مباشرة').click();
  await page.getByTestId('review').locator('button').click();
  await page.getByTestId('confirm').locator('button').click();
  await expect(page.getByTestId('vehicle-status')).toContainText('متاحة');

  const matches = page.getByTestId('vehicle-matches');
  await expect(matches).toContainText('1 عميل طلبوا عربية زي دي');
  await expect(matches).toContainText('كريم محمود');
  await expect(matches).toContainText('+201001112233');
  await matches.getByRole('button', { name: 'تم التواصل' }).click();
  await expect(matches.getByText('تم التواصل')).toBeVisible();
});

test('receives a consigned car, sells it and pays the owner', async ({ page }) => {
  test.setTimeout(180_000);
  await page.goto(`/t/${NOUR}/consignments`);
  await page.getByTestId('receive-consignment').locator('button').click();
  await pick(page, 'cf-owner', 'سمير', /سمير عادل/);
  await page.getByTestId('cf-make').fill('Renault');
  await page.getByTestId('cf-model').fill('Megane');
  await money(page, 'cf-asking', '300000');
  await money(page, 'cf-value', '5');
  await page.getByTestId('cf-save').locator('button').click();
  await expect(page.getByTestId('consignment-title')).toContainText('Renault Megane');
  await expect(page.getByTestId('consignment-status')).toContainText('معروضة');

  await page.getByRole('link', { name: /^V-/ }).click();
  await expect(page.getByTestId('consignment-notice')).toContainText('سيارة أمانة لـ سمير عادل');
  await expect(page.getByTestId('record-purchase')).toHaveCount(0);
  await page.getByTestId('to-AVAILABLE').locator('button').click();
  await expect(page.getByTestId('vehicle-status')).toContainText('متاحة');

  await page.getByTestId('sell').locator('button').click();
  await expect(page.getByTestId('sale-consigned')).toContainText('سمير عادل');
  await expect(page.getByTestId('installments-section')).toHaveCount(0);
  await pick(page, 'buyer-picker', 'حسن', /حسن علي/);
  await money(page, 'payment-amount-0', '300000');
  await page.getByTestId('post-sale').locator('button').click();
  await expect(page.getByTestId('preview-summary')).toContainText('عمولة المعرض');
  await expect(page.getByTestId('preview-summary')).toContainText('285,000.00');
  await page.getByTestId('confirm').locator('button').click();
  await expect(page.getByTestId('sale-status')).toContainText('مرحّل');
  await expect(page.getByTestId('sale-commission')).toContainText('15,000.00');
  await expect(page.getByTestId('sale-due-owner')).toContainText('285,000.00');

  await page.goto(`/t/${NOUR}/consignments`);
  await page.getByTestId('consignments-in').getByRole('link', { name: 'Renault Megane' }).first().click();
  await expect(page.getByTestId('due-to-owner')).toContainText('285,000.00');
  await page.getByTestId('pay-owner').locator('button').click();
  await page.getByTestId('review').locator('button').click();
  await expect(page.getByTestId('preview-summary')).toContainText('سمير عادل');
  await page.getByTestId('confirm').locator('button').click();
  await expect(page.getByTestId('due-to-owner')).toContainText('0.00');
});
