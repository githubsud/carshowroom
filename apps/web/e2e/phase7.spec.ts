import { expect, Page, test } from '@playwright/test';

import { AS_OWNER, AS_SALES, NOUR } from './helpers';

/**
 * Phase 7 through the UI: the MVP acceptance demo of SPEC §13 (BACKLOG 7.9),
 * the reports centre and closing a period with its profit distribution.
 *
 * The demo starts from the seeded showroom and its three partners: creating a
 * showroom from the UI is the onboarding wizard of Phase 8 (D-105).
 */

async function money(page: Page, testId: string, value: string): Promise<void> {
  await page.getByTestId(testId).locator('input').fill(value);
}

async function choose(page: Page, testId: string, option: string): Promise<void> {
  await page.getByTestId(testId).click();
  await page.getByRole('option', { name: option, exact: true }).click();
}

async function pick(page: Page, testId: string, query: string, option: RegExp): Promise<void> {
  await page.getByTestId(testId).locator('input').fill(query);
  await page.getByRole('option', { name: option }).click();
}

async function reviewAndConfirm(page: Page): Promise<void> {
  await page.getByTestId('review').locator('button').click();
  await page.getByTestId('confirm').locator('button').click();
}

async function expense(page: Page, chip: string, amount: string): Promise<void> {
  await page.getByTestId('add-expense').locator('button').click();
  await page.getByTestId('expense-chips').getByText(chip, { exact: true }).click();
  await money(page, 'amount', amount);
  await reviewAndConfirm(page);
}

test.use({ storageState: AS_OWNER });

test('MVP acceptance demo (SPEC §13)', async ({ page, browser }) => {
  test.setTimeout(300_000);
  const run = Date.now().toString(36);
  const make = `Demo${run}`;

  // Partners record their capital (rule 1).
  await page.goto(`/t/${NOUR}/partners`);
  for (const [name, amount] of [
    ['أحمد السيد', '50000'],
    ['منى عبد الله', '30000'],
    ['يوسف حسن', '20000'],
  ]) {
    await page.getByTestId('new-partner-txn').locator('button').click();
    await choose(page, 'txn-partner', name);
    await choose(page, 'txn-type', 'مساهمة في رأس المال');
    await money(page, 'amount', amount);
    await reviewAndConfirm(page);
    await expect(page.getByText(/تم التسجيل — قيد رقم \d+/).first()).toBeVisible();
  }

  // A car is bought, with transport, repair and licence expenses; the true cost shows.
  await page.goto(`/t/${NOUR}/vehicles`);
  await page.getByTestId('add-vehicle').locator('button').click();
  // The dialog focuses its first field once open; type only after that.
  await expect(page.getByTestId('vehicle-make')).toBeFocused();
  await page.getByTestId('vehicle-make').fill(make);
  await page.getByTestId('vehicle-model').fill('Sedan');
  await page.getByTestId('vehicle-year').fill('2021');
  await money(page, 'asking-price', '400000');
  await page.getByTestId('vehicle-save').locator('button').click();
  await pick(page, 'seller-picker', 'كريم', /كريم محمود/);
  await money(page, 'purchase-price', '300000');
  await money(page, 'paid-now', '300000');
  await page.getByText('جاهزة للبيع مباشرة').click();
  await reviewAndConfirm(page);
  await expect(page.getByTestId('total-cost')).toContainText('300,000.00');
  await expense(page, 'نقل', '2000');
  await expense(page, 'صيانة', '8000');
  await expense(page, 'تجديد رخصة', '1500');
  await expect(page.getByTestId('total-cost')).toContainText('311,500.00');
  const vehicleUrl = page.url();

  // Staff add a customer and a car request; the system shows the match.
  const staff = await browser.newContext({ storageState: AS_SALES });
  const sales = await staff.newPage();
  await sales.goto(`/t/${NOUR}/requests`);
  await sales.getByTestId('add-request').locator('button').click();
  await sales.getByTestId('rq-customer-add').locator('button').click();
  await sales.getByTestId('customer-name').fill(`عميل التجربة ${run}`);
  await sales.getByTestId('customer-phone').fill(`0109${Date.now().toString().slice(-7)}`);
  await sales.getByTestId('customer-save').locator('button').click();
  await sales.getByTestId('rq-make').fill(make);
  await money(sales, 'rq-budget', '450000');
  await sales.getByTestId('rq-save').locator('button').click();
  await expect(sales.getByText('تم حفظ الطلب — 1 سيارة مناسبة الآن')).toBeVisible();
  await staff.close();

  await page.goto(vehicleUrl);
  await expect(page.getByTestId('vehicle-matches')).toContainText(`عميل التجربة ${run}`);

  // The customer pays a deposit, then the sale is posted with a down payment and installments.
  await page.getByTestId('reserve').locator('button').click();
  await pick(page, 'reservation-customer', `التجربة ${run}`, new RegExp(`عميل التجربة ${run}`));
  await money(page, 'amount', '20000');
  await reviewAndConfirm(page);
  await expect(page.getByTestId('vehicle-status')).toContainText('محجوزة');

  await page.getByTestId('sell').locator('button').click();
  await expect(page.getByTestId('deposit-applied')).toContainText('20,000.00');
  await money(page, 'payment-amount-0', '80000');
  await page.getByTestId('use-installments').click();
  await page.getByTestId('inst-count').fill('3');
  await page.getByTestId('show-schedule').locator('button').click();
  await expect(page.getByTestId('financed')).toContainText('300,000.00');
  await page.getByTestId('post-sale').locator('button').click();
  await page.getByTestId('confirm').locator('button').click();
  await expect(page.getByTestId('sale-status')).toContainText('مرحّل');

  // The car's profit is shown: 400,000 - 311,500.
  await expect(page.getByTestId('sale-profit')).toContainText('88,500.00');

  // The first installment is collected.
  await page.getByTestId('plan-link').click();
  await page.getByTestId('collect').locator('button').click();
  await money(page, 'amount', '100000');
  await reviewAndConfirm(page);
  await expect(page.getByTestId('seq-1')).toContainText('مدفوع');

  // Dashboard: cash and partner balances, due payments, aging stock and Needs Attention.
  await page.goto(`/t/${NOUR}/dashboard`);
  await expect(page.getByTestId('kpi-cash')).toBeVisible();
  await expect(page.getByTestId('equity-matrix')).toContainText('أحمد السيد');
  await expect(page.getByTestId('installment-tiles')).toBeVisible();
  await expect(page.getByTestId('kpi-aged')).toBeVisible();
  const attention = page.getByTestId('needs-attention');
  await expect(attention).toBeVisible();
  await expect(attention.getByTestId('attention-INSTALLMENT_OVERDUE').first()).toBeVisible();
  await expect(attention.getByTestId('attention-FOLLOW_UP_DUE').first()).toBeVisible();
});

test('reports centre shows the profit and loss and exports Excel', async ({ page }) => {
  await page.goto(`/t/${NOUR}/reports`);
  await page.getByTestId('report-profit-and-loss').click();
  await page.getByTestId('report-from').fill('2026-09-01');
  await page.getByTestId('report-to').fill('2026-09-30');
  await page.getByTestId('report-run').locator('button').click();
  await expect(page.getByTestId('report-table')).toContainText('صافي الربح');
  await expect(page.getByTestId('report-figures')).toContainText('57,000.00');

  await page.getByTestId('report-inventory-aging').click();
  await expect(page.getByTestId('report-table')).toContainText('V-');
  const [download] = await Promise.all([
    page.waitForEvent('download'),
    page.getByTestId('report-xlsx').locator('button').click(),
  ]);
  expect(download.suggestedFilename()).toBe('inventory-aging.xlsx');
});

test('closes September, distributes 57,000 by 50/30/20, then reverses it', async ({ page }) => {
  await page.goto(`/t/${NOUR}/distribution`);
  await page.getByTestId('dist-from').fill('2026-09-01');
  await page.getByTestId('dist-to').fill('2026-09-30');
  await page.getByTestId('dist-preview').locator('button').click();
  await expect(page.getByTestId('dist-net')).toContainText('57,000.00');
  const lines = page.getByTestId('dist-lines');
  await expect(lines).toContainText('28,500.00');
  await expect(lines).toContainText('17,100.00');
  await expect(lines).toContainText('11,400.00');
  await page.getByTestId('dist-confirm').locator('button').click();
  await expect(page.getByText('تم إقفال الفترة وتوزيع الأرباح')).toBeVisible();

  const history = page.getByTestId('distributions');
  await expect(history).toContainText('مُوزَّع');
  // Leave the seed as it was for the other tests: undo the distribution.
  await history.getByRole('button', { name: 'عكس التوزيع' }).click();
  await page.locator('#rev-reason').fill('تجربة آلية');
  await page.getByRole('dialog').getByRole('button', { name: 'عكس التوزيع' }).click();
  await expect(history).toContainText('معكوس');
});
