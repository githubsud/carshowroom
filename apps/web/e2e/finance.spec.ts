import { expect, Page, test } from '@playwright/test';

import { amountOf, AS_ACCOUNTANT, AS_OWNER, AS_SALES, NOUR } from './helpers';

/**
 * Phase 2 through the UI: record an expense and a transfer with a plain-language
 * preview, see balances and the cash book update, export Excel, reverse an entry
 * with a reason, and lock/unlock a month — each by the right role only.
 */

async function balance(page: Page, code: string): Promise<number> {
  return amountOf(await page.getByTestId(`balance-${code}`).locator('.amount').textContent());
}

async function choose(page: Page, testId: string, option: string): Promise<void> {
  await page.getByTestId(testId).click();
  await page.getByRole('option', { name: option }).click();
}

test.describe('owner', () => {
  test.use({ storageState: AS_OWNER });

  test('records an expense typed with Arabic digits, after a plain-language preview', async ({ page }) => {
    await page.goto(`/t/${NOUR}/finance/cash`);
    await expect(page.getByTestId('balances')).toBeVisible();
    const before = await balance(page, '1101');

    await page.getByTestId('new-expense').locator('button').click();
    await choose(page, 'expense-category', 'إيجار');
    await page.getByTestId('amount').locator('input').fill('١٢٣٤٫٥٠'); // 1234.50 on an Arabic keyboard
    await page.getByTestId('review').locator('button').click();

    await expect(page.getByTestId('preview-summary')).toContainText('سيتم خصم 1,234.50 ج.م من «الخزنة الرئيسية»');
    await page.getByTestId('confirm').locator('button').click();

    await expect(page.getByText(/تم التسجيل — قيد رقم \d+/)).toBeVisible();
    await expect.poll(() => balance(page, '1101')).toBeCloseTo(before - 1234.5, 2);
    await expect(page.getByTestId('cash-book')).toContainText('إيجار');
  });

  test('moves money from the cash box to the bank', async ({ page }) => {
    await page.goto(`/t/${NOUR}/finance/cash`);
    await expect(page.getByTestId('balances')).toBeVisible();
    const cashBefore = await balance(page, '1101');
    const bankBefore = await balance(page, '1201');

    await page.getByTestId('new-transfer').locator('button').click();
    await page.getByTestId('amount').locator('input').fill('500');
    await page.getByTestId('review').locator('button').click();
    await expect(page.getByTestId('preview-summary')).toContainText('سيتم تحويل 500.00 ج.م من «الخزنة الرئيسية» إلى «بنك CIB»');
    await page.getByTestId('confirm').locator('button').click();

    await expect.poll(() => balance(page, '1101')).toBeCloseTo(cashBefore - 500, 2);
    await expect.poll(() => balance(page, '1201')).toBeCloseTo(bankBefore + 500, 2);
  });

  test('downloads the cash book as Excel', async ({ page }) => {
    await page.goto(`/t/${NOUR}/finance/cash`);
    await expect(page.getByTestId('cash-book')).toBeVisible();
    const [download] = await Promise.all([
      page.waitForEvent('download'),
      page.getByTestId('export-xlsx').locator('button').click(),
    ]);
    expect(download.suggestedFilename()).toMatch(/^cash-book-1101-.*\.xlsx$/);
  });

  test('locks a month and unlocks it with a reason', async ({ page }) => {
    await page.goto(`/t/${NOUR}/finance/periods`);
    await page.getByTestId('lock-month').fill('2025-03');
    await page.getByTestId('lock-submit').locator('button').click();
    const row = page.getByTestId('period-2025-03');
    await expect(row).toContainText('مقفول');

    await page.getByTestId('unlock-2025-03').locator('button').click();
    await page.getByTestId('unlock-reason').fill('تصحيح بعد المراجعة');
    await page.getByTestId('unlock-confirm').locator('button').click();
    await expect(row).toContainText('مفتوح');
  });
});

test.describe('accountant', () => {
  test.use({ storageState: AS_ACCOUNTANT });

  test('reverses the latest entry with a reason', async ({ page }) => {
    await page.goto(`/t/${NOUR}/finance/journal`);
    const firstRow = page.getByTestId('journal-table').locator('tbody tr').first();
    await expect(firstRow).toBeVisible();
    const entryNo = (await firstRow.locator('td').first().textContent())?.trim();

    await firstRow.click();
    await expect(page.getByTestId('entry-lines')).toContainText('مدين');
    await page.getByTestId('reverse-start').locator('button').click();
    await page.getByTestId('reverse-reason').fill('تسجيل بالخطأ');
    await page.getByTestId('reverse-review').locator('button').click();
    await expect(page.getByTestId('preview-summary')).toContainText(`القيد رقم ${entryNo}`);
    await page.getByTestId('reverse-confirm').locator('button').click();

    await expect(page.getByText(new RegExp(`تم عكس القيد ${entryNo} بالقيد \\d+`))).toBeVisible();
    await expect(page.getByTestId('journal-table')).toContainText(`اتعكس بالقيد`);
  });

  test('can see months but not lock or unlock them', async ({ page }) => {
    await page.goto(`/t/${NOUR}/finance/periods`);
    await expect(page.getByTestId('periods-table')).toBeVisible();
    await expect(page.getByTestId('lock-submit')).toHaveCount(0);
  });
});

test.describe('sales staff', () => {
  test.use({ storageState: AS_SALES });

  test('have no access to cash, journal or month lock', async ({ page }) => {
    for (const path of ['finance/cash', 'finance/journal', 'finance/periods', 'settings/finance']) {
      await page.goto(`/t/${NOUR}/${path}`);
      await expect(page).toHaveURL(new RegExp(`/t/${NOUR}/dashboard$`));
    }
  });
});
