import { expect, Page, test } from '@playwright/test';

import { amountOf, AS_OWNER, AS_PARTNER, NOUR } from './helpers';

/**
 * Phase 3 through the UI: every partner's balance in one screen, partner
 * movements with a plain-language preview, statements, ownership changes,
 * rule 30 and other income — and a partner user who sees only their own.
 */

const MONA = 'f0000000-0000-0000-0000-000000000002';
const YOUSEF = 'f0000000-0000-0000-0000-000000000003';

async function choose(page: Page, testId: string, option: string): Promise<void> {
  await page.getByTestId(testId).click();
  await page.getByRole('option', { name: option, exact: true }).click();
}

function row(page: Page, partnerId: string) {
  return page.getByTestId(`partner-row-${partnerId}`);
}

test.describe('owner', () => {
  test.use({ storageState: AS_OWNER });

  test('sees every partner balance in one screen', async ({ page }) => {
    await page.goto(`/t/${NOUR}/partners`);
    const table = page.getByTestId('partners-summary');
    await expect(table).toContainText('أحمد السيد');
    await expect(row(page, MONA)).toContainText('30%');
    await expect(table.locator('tfoot')).toContainText('100%');
  });

  test('records a drawing after a preview and the summary updates', async ({ page }) => {
    await page.goto(`/t/${NOUR}/partners`);
    const drawingsBefore = amountOf(await row(page, MONA).locator('td').nth(5).textContent());

    await page.getByTestId('new-partner-txn').locator('button').click();
    await choose(page, 'txn-partner', 'منى عبد الله');
    await choose(page, 'txn-type', 'مسحوبات من الحصة');
    await page.getByTestId('amount').locator('input').fill('2000');
    await page.getByTestId('review').locator('button').click();
    await expect(page.getByTestId('preview-summary')).toContainText('وتسجيلها كـمسحوبات من الحصة للشريك منى عبد الله');
    await page.getByTestId('confirm').locator('button').click();

    await expect(page.getByText(/تم التسجيل — قيد رقم \d+/)).toBeVisible();
    await expect.poll(async () => amountOf(await row(page, MONA).locator('td').nth(5).textContent())).toBeCloseTo(
      drawingsBefore + 2000,
      2,
    );
  });

  test('opens a partner statement and exports it', async ({ page }) => {
    await page.goto(`/t/${NOUR}/partners`);
    await row(page, MONA).click();
    await expect(page).toHaveURL(new RegExp(`/partners/${MONA}$`));
    await expect(page.getByTestId('statement-title')).toContainText('منى عبد الله');
    await expect(page.getByTestId('statement-lines')).toContainText('300,000.00');
    const [download] = await Promise.all([
      page.waitForEvent('download'),
      page.getByTestId('statement-xlsx').locator('button').click(),
    ]);
    expect(download.suggestedFilename()).toMatch(/^partner-statement-.*\.xlsx$/);
  });

  test('ownership dialog totals 100% and splits thirds exactly', async ({ page }) => {
    await page.goto(`/t/${NOUR}/partners`);
    await page.getByTestId('change-shares').locator('button').click();
    await expect(page.getByTestId('shares-total')).toHaveText('100.0000%');
    await page.getByTestId('share-0').fill('60');
    await expect(page.getByTestId('shares-total')).toHaveText('110.0000%');
    await expect(page.getByTestId('shares-save').locator('button')).toBeDisabled();
    await page.getByRole('button', { name: 'توزيع بالتساوي' }).click();
    await expect(page.getByTestId('share-0')).toHaveValue('33.3334');
    await expect(page.getByTestId('shares-total')).toHaveText('100.0000%');
  });

  test('records an expense paid personally by a partner, and other income', async ({ page }) => {
    await page.goto(`/t/${NOUR}/finance/cash`);
    await expect(page.getByTestId('balances')).toBeVisible();

    await page.getByTestId('new-expense').locator('button').click();
    await choose(page, 'expense-category', 'مرافق');
    await page.getByTestId('amount').locator('input').fill('800');
    await page.getByTestId('funding').getByText('دفعه شريك من جيبه').click();
    await choose(page, 'paid-by-partner', 'أحمد السيد');
    await page.getByTestId('review').locator('button').click();
    await expect(page.getByTestId('preview-summary')).toContainText('دفعه الشريك أحمد السيد من ماله الخاص');
    await expect(page.getByTestId('preview-summary')).toContainText('الخزنة لن تتأثر');
    await page.getByTestId('confirm').locator('button').click();
    await expect(page.getByText(/تم التسجيل — قيد رقم \d+/)).toBeVisible();

    await page.getByTestId('new-income').locator('button').click();
    await page.getByTestId('amount').locator('input').fill('1500');
    await page.getByTestId('note').fill('عمولة وساطة');
    await page.getByTestId('review').locator('button').click();
    await expect(page.getByTestId('preview-summary')).toContainText('كإيراد آخر «عمولة وساطة»');
    await page.getByTestId('confirm').locator('button').click();
    await expect(page.getByText(/تم التسجيل — قيد رقم \d+/).first()).toBeVisible();
  });
});

test.describe('partner user', () => {
  test.use({ storageState: AS_PARTNER });

  test('lands on their own statement and sees their position on the dashboard', async ({ page }) => {
    await page.goto(`/t/${NOUR}/dashboard`);
    await expect(page.getByTestId('my-position')).toContainText('200,000.00');

    await page.getByTestId('nav-partners').click();
    await expect(page).toHaveURL(new RegExp(`/partners/${YOUSEF}$`));
    await expect(page.getByTestId('statement-title')).toContainText('يوسف حسن');
    await expect(page.getByTestId('statement-new-txn')).toHaveCount(0);

    // Another partner's statement is refused by the API.
    await page.goto(`/t/${NOUR}/partners/${MONA}`);
    await expect(page.getByRole('alert')).toBeVisible();
  });
});
