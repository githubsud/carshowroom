import { expect, test } from '@playwright/test';

import { AS_OWNER, NOUR } from './helpers';

/**
 * Phase 8 through the UI: a messy sheet is checked with clear errors and
 * nothing saved; the fixed sheet imports with one opening entry; onboarding
 * walks from the profile to the opening entry.
 */

test.use({ storageState: AS_OWNER });

function csv(vin: string, broken: boolean): Buffer {
  const lines = [
    'كشف العربيات',
    '',
    'الماركه,الموديل,سنه الصنع,رقم الشاسية,سعر الشراء,نقل',
    `Chery,Tiggo,٢٠٢٢,${vin},"٣٥٠٬٠٠٠",EGP 3000`,
  ];
  if (broken) {
    lines.push(',Arrizo,2021,ABCD9999,abc,');
  }
  return Buffer.from('﻿' + lines.join('\n'), 'utf-8');
}

test('a messy sheet shows its errors, the fixed one imports with one opening entry', async ({ page }) => {
  test.setTimeout(120_000);
  const vin = `LVVDB${Date.now().toString().slice(-12)}`;
  await page.goto(`/t/${NOUR}/import`);
  await page.getByTestId('import-file').setInputFiles({ name: 'stock.csv', mimeType: 'text/csv', buffer: csv(vin, true) });
  await expect(page.getByTestId('sheet-0')).toBeVisible();
  await page.getByTestId('import-check').locator('button').click();
  await expect(page.getByTestId('result-0')).toContainText('1 صف سليم');
  const errors = page.getByTestId('errors-0');
  await expect(errors).toContainText('صف 5');
  await expect(errors).toContainText('الماركة: مطلوب');
  await expect(errors).toContainText('سعر الشراء: رقم غير صحيح');
  await expect(page.getByTestId('import-commit')).toHaveCount(0);

  await page.goto(`/t/${NOUR}/import`);
  await page.getByTestId('import-file').setInputFiles({ name: 'stock.csv', mimeType: 'text/csv', buffer: csv(vin, false) });
  await expect(page.getByTestId('sheet-0')).toBeVisible();
  await page.getByTestId('import-check').locator('button').click();
  await expect(page.getByTestId('result-0')).toContainText('1 صف سليم');
  await page.getByTestId('import-commit').locator('button').click();
  await expect(page.getByTestId('import-done')).toContainText('1 سيارة');
  await expect(page.getByTestId('import-done')).toContainText(/قيد الأرصدة الافتتاحية رقم \d+/);
});

test('onboarding walks from the profile to the opening entry', async ({ page }) => {
  test.setTimeout(120_000);
  await page.goto(`/t/${NOUR}/onboarding`);
  await expect(page.getByTestId('onb-name')).toHaveValue('معرض النور للسيارات');
  await page.getByTestId('onb-next').locator('button').click();

  // Partners are already set up in this showroom: leave the step empty.
  await page.getByTestId('onb-partner-name-0').fill('');
  await page.getByTestId('onb-next').locator('button').click();

  await page.getByTestId('onb-cash-name-0').fill('');
  await page.getByTestId('onb-cash-name-1').fill(`بنك تجربة ${Date.now().toString(36)}`);
  await page.getByTestId('onb-cash-balance-1').fill('1,000');
  await page.getByTestId('onb-next').locator('button').click();
  await page.getByTestId('onb-next').locator('button').click();

  await page.getByTestId('import-check').locator('button').click();
  await page.getByTestId('import-commit').locator('button').click();
  await expect(page.getByTestId('onb-done')).toContainText(/قيد الأرصدة الافتتاحية رقم \d+/);
});
