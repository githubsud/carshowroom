import { expect, Page, test } from '@playwright/test';

import { AS_OWNER, NOUR } from './helpers';

/**
 * Phase 5 through the UI: an installment sale with its schedule, collections,
 * the overdue board and calendar, and a post-dated cheque that is collected
 * and then bounces (rule 27).
 */

const OMAR_PLAN = 'd3000000-0000-0000-0000-000000000001';

async function money(page: Page, testId: string, value: string): Promise<void> {
  await page.getByTestId(testId).locator('input').fill(value);
}

async function choose(page: Page, testId: string, option: string): Promise<void> {
  await page.getByTestId(testId).click();
  await page.getByRole('option', { name: option, exact: true }).click();
}

test.use({ storageState: AS_OWNER });

test('sells a car on installments and collects the first one', async ({ page }) => {
  test.setTimeout(180_000);
  await page.goto(`/t/${NOUR}/vehicles`);
  await page.getByTestId('add-vehicle').locator('button').click();
  // The dialog focuses its first field once open; type only after that.
  await expect(page.getByTestId('vehicle-make')).toBeFocused();
  await page.getByTestId('vehicle-make').fill('Hyundai');
  await page.getByTestId('vehicle-model').fill('Tucson');
  await page.getByTestId('vehicle-year').fill('2022');
  await money(page, 'asking-price', '360000');
  await page.getByTestId('vehicle-save').locator('button').click();
  await page.getByTestId('seller-picker').locator('input').fill('كريم');
  await page.getByRole('option', { name: /كريم محمود/ }).click();
  await money(page, 'purchase-price', '300000');
  await money(page, 'paid-now', '300000');
  await page.getByText('جاهزة للبيع مباشرة').click();
  await page.getByTestId('review').locator('button').click();
  await page.getByTestId('confirm').locator('button').click();
  await expect(page.getByTestId('vehicle-title')).toContainText('Hyundai Tucson 2022');

  await page.getByTestId('sell').locator('button').click();
  await page.getByTestId('buyer-picker').locator('input').fill('حسن');
  await page.getByRole('option', { name: /حسن علي/ }).click();
  await money(page, 'payment-amount-0', '60000');
  await page.getByTestId('use-installments').click();
  await page.getByTestId('inst-count').fill('6');
  await page.getByTestId('show-schedule').locator('button').click();
  await expect(page.getByTestId('financed')).toContainText('300,000.00');
  await expect(page.getByTestId('schedule-preview').locator('li')).toHaveCount(6);
  await expect(page.getByTestId('schedule-preview')).toContainText('50,000.00');
  await expect(page.getByTestId('remaining')).toContainText('0.00');

  await page.getByTestId('post-sale').locator('button').click();
  await expect(page.getByTestId('preview-summary')).toContainText('على 6 قسط');
  await page.getByTestId('confirm').locator('button').click();
  await expect(page.getByTestId('sale-status')).toContainText('مرحّل');

  await page.getByTestId('plan-link').click();
  await expect(page.getByTestId('plan-title')).toContainText('حسن علي');
  await expect(page.getByTestId('plan-remaining')).toContainText('300,000.00');
  await page.getByTestId('collect').locator('button').click();
  await money(page, 'amount', '50000');
  await page.getByTestId('review').locator('button').click();
  await expect(page.getByTestId('preview-summary')).toContainText('القسط 1');
  await page.getByTestId('confirm').locator('button').click();
  await expect(page.getByTestId('seq-1')).toContainText('مدفوع');
  await expect(page.getByTestId('plan-remaining')).toContainText('250,000.00');
});

test('the board lists overdue installments with days late and the calendar shows them', async ({ page }) => {
  await page.goto(`/t/${NOUR}/installments`);
  const row = page.getByTestId('installment-S-2026-0002-1');
  await expect(row).toContainText('عمر خالد');
  await expect(row.getByTestId('days-late')).toContainText('يوم');
  await expect(page.getByTestId('per-customer')).toContainText('عمر خالد');

  await page.getByTestId('installment-view').getByText('التقويم').click();
  await expect(page.getByTestId('calendar')).toBeVisible();

  await page.goto(`/t/${NOUR}/dashboard`);
  await expect(page.getByTestId('installment-tiles')).toBeVisible();
  await expect(page.getByTestId('dashboard-overdue')).not.toContainText(/^0\.00/);
});

test('a collected cheque that bounces reopens the installment and notifies', async ({ page }) => {
  test.setTimeout(180_000);
  const number = `E2E${Date.now().toString().slice(-7)}`;
  await page.goto(`/t/${NOUR}/installments/plans/${OMAR_PLAN}`);
  await expect(page.getByTestId('plan-title')).toContainText('عمر خالد');
  const firstOpen = page.getByTestId('schedule').locator('tbody tr').filter({ hasNotText: 'مدفوع' }).first();
  const seq = (await firstOpen.locator('td').first().textContent())?.trim() ?? '';

  await page.getByTestId('add-paper').locator('button').click();
  await page.getByTestId('paper-number').fill(number);
  await page.getByTestId('paper-save').locator('button').click();

  const act = async (action: string) => {
    await page.getByTestId(`paper-act-${number}`).locator('button').click();
    await choose(page, 'paper-action', action);
    await page.getByTestId('review').locator('button').click();
    await expect(page.getByTestId('preview-summary')).toBeVisible();
    await page.getByTestId('confirm').locator('button').click();
    await expect(page.getByTestId('paper-action-form')).toHaveCount(0);
  };

  await act('إيداع بالبنك');
  await act('تحصيل');
  await expect(page.getByTestId(`seq-${seq}`)).toContainText('مدفوع');
  await act('ارتداد');
  await expect(page.getByTestId(`seq-${seq}`)).not.toContainText('مدفوع');
  await expect(page.getByTestId('plan-papers')).toContainText('مرتد');

  await page.getByTestId('notification-bell').click();
  await expect(page.getByTestId('notifications')).toContainText(`ارتد الشيك رقم ${number}`);
});
