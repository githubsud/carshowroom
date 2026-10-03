import { expect, Page, test } from '@playwright/test';

import { amountOf, AS_OWNER, AS_SALES, NOUR } from './helpers';

/**
 * Phase 4 through the UI: the full purchase -> expenses -> sale cycle posts
 * and the vehicle file shows exact cost and profit (SPEC §13); sales staff
 * never see cost; quick search; phone-first customers.
 */

const ELANTRA = 'e1000000-0000-0000-0000-000000000001';

async function pickCustomer(page: Page, testId: string, query: string, option: RegExp): Promise<void> {
  await page.getByTestId(testId).locator('input').fill(query);
  await page.getByRole('option', { name: option }).click();
}

async function money(page: Page, testId: string, value: string): Promise<void> {
  await page.getByTestId(testId).locator('input').fill(value);
}

async function reviewAndConfirm(page: Page): Promise<void> {
  await page.getByTestId('review').locator('button').click();
  await expect(page.getByTestId('preview-summary')).toBeVisible();
  await page.getByTestId('confirm').locator('button').click();
}

test.describe('owner', () => {
  test.use({ storageState: AS_OWNER });

  test('buys, prepares, reserves, sells with a trade-in, then cancels a car', async ({ page }) => {
    test.setTimeout(180_000);
    const vin = `JM1GJ${Date.now().toString().slice(-12)}`;

    // 1. Add-car wizard: details, then the purchase (rules 6/7).
    await page.goto(`/t/${NOUR}/vehicles`);
    await page.getByTestId('add-vehicle').locator('button').click();
    // The dialog focuses its first field once open; type only after that.
    await expect(page.getByTestId('vehicle-make')).toBeFocused();
    await page.getByTestId('vehicle-make').fill('Mazda');
    await page.getByTestId('vehicle-model').fill('6');
    await page.getByTestId('vehicle-year').fill('2017');
    await page.getByTestId('vehicle-vin').fill(vin);
    await money(page, 'asking-price', '260000');
    await page.getByTestId('vehicle-save').locator('button').click();

    await pickCustomer(page, 'seller-picker', 'كريم', /كريم محمود/);
    await money(page, 'purchase-price', '200000');
    await money(page, 'paid-now', '200000');
    await page.getByText('جاهزة للبيع مباشرة').click();
    await reviewAndConfirm(page);

    await expect(page.getByTestId('vehicle-title')).toContainText('Mazda 6 2017');
    await expect(page.getByTestId('vehicle-status')).toContainText('متاحة للبيع');
    await expect(page.getByTestId('total-cost')).toContainText('200,000.00');

    // 2. Quick expense (rule 9): it is added to the car's cost.
    await page.getByTestId('add-expense').locator('button').click();
    await page.getByTestId('expense-chips').getByText('دهان').click();
    await money(page, 'amount', '5000');
    await page.getByTestId('review').locator('button').click();
    await expect(page.getByTestId('preview-summary')).toContainText('تُضاف إلى تكلفة السيارة');
    await page.getByTestId('confirm').locator('button').click();
    await expect(page.getByTestId('total-cost')).toContainText('205,000.00');

    // 3. Reservation with a deposit (rule 11).
    await page.getByTestId('reserve').locator('button').click();
    await pickCustomer(page, 'reservation-customer', 'حسن', /حسن علي/);
    await money(page, 'amount', '10000');
    await reviewAndConfirm(page);
    await expect(page.getByTestId('vehicle-status')).toContainText('محجوزة');
    await expect(page.getByTestId('reservation')).toContainText('حسن علي');

    // 4. Sale: discount, deposit applied, trade-in, cash + bank (rules 12, 26).
    await page.getByTestId('sell').locator('button').click();
    await expect(page.getByTestId('sale-vehicle')).toContainText('Mazda 6 2017');
    await expect(page.getByTestId('deposit-applied')).toContainText('10,000.00');
    await money(page, 'discount', '10000');
    await expect(page.getByTestId('net-price')).toContainText('250,000.00');
    await page.getByTestId('has-trade-in').click();
    await page.getByTestId('trade-make').fill('Kia');
    await page.getByTestId('trade-model').fill('Rio');
    await money(page, 'trade-value', '50000');
    await money(page, 'payment-amount-0', '90000');
    await page.getByTestId('add-payment').locator('button').click();
    await page.getByTestId('payment-1').locator('p-select').click();
    await page.getByRole('option', { name: 'بنك CIB' }).click();
    await expect(page.getByTestId('remaining')).toContainText('0.00');

    await page.getByTestId('post-sale').locator('button').click();
    await expect(page.getByTestId('preview-summary')).toContainText('سيتم بيع Mazda 6 2017');
    await expect(page.getByTestId('preview-summary')).toContainText('سيارة العميل Kia Rio');
    await page.getByTestId('confirm').locator('button').click();
    await expect(page.getByTestId('sale-status')).toContainText('مرحّل');
    await expect(page.getByTestId('sale-title')).toContainText(/INV-\d{4}-\d{5}/);
    await expect(page.getByTestId('sale-profit')).toContainText('45,000.00');

    // 5. Cancellation (D-41 default: what the customer paid becomes owed to them).
    await page.getByTestId('cancel-sale').locator('button').click();
    await page.getByTestId('cancel-reason').fill('العميل غيّر رأيه');
    await page.getByTestId('review').locator('button').click();
    await expect(page.getByTestId('preview-summary')).toContainText('يصبح مستحقاً له');
    await page.getByTestId('confirm').locator('button').click();
    await expect(page.getByTestId('sale-status')).toContainText('ملغي');
    await page.getByTestId('sale-vehicle').click();
    await expect(page.getByTestId('vehicle-status')).toContainText('متاحة للبيع');
    await expect(page.getByTestId('total-cost')).toContainText('205,000.00');
  });

  test('quick search finds a car by the last digits of its VIN', async ({ page }) => {
    await page.goto(`/t/${NOUR}/dashboard`);
    await page.getByTestId('global-search').fill('U123456');
    await page.getByTestId('search-results').getByText('Hyundai Elantra 2019').click();
    await expect(page).toHaveURL(new RegExp(`/vehicles/${ELANTRA}$`));
    await expect(page.getByTestId('cost-section')).toBeVisible();
    expect(amountOf(await page.getByTestId('total-cost').textContent())).toBeGreaterThanOrEqual(415000);
  });

  test('a known phone number offers the existing customer instead of a duplicate', async ({ page }) => {
    await page.goto(`/t/${NOUR}/customers`);
    await page.getByTestId('add-customer').locator('button').click();
    await page.getByTestId('customer-name').fill('كريم');
    await page.getByTestId('customer-phone').fill('0100 111 2233');
    await page.getByTestId('customer-save').locator('button').click();
    await expect(page.getByTestId('dialog-error')).toContainText('يوجد عميل بنفس رقم الهاتف');
    await page.getByTestId('use-existing').locator('button').click();
    await expect(page.getByTestId('customer-title')).toContainText('كريم محمود');
  });
});

test.describe('sales staff', () => {
  test.use({ storageState: AS_SALES });

  test('see cars, prices and photos but never cost or profit', async ({ page }) => {
    await page.goto(`/t/${NOUR}/vehicles`);
    await expect(page.getByTestId('inventory')).toContainText('Elantra');
    await expect(page.getByTestId('row-cost')).toHaveCount(0);

    await page.goto(`/t/${NOUR}/vehicles/${ELANTRA}`);
    await expect(page.getByTestId('vehicle-title')).toContainText('Hyundai Elantra 2019');
    await expect(page.getByTestId('asking')).toContainText('480,000.00');
    await expect(page.getByTestId('cost-section')).toHaveCount(0);
    await expect(page.getByTestId('add-expense')).toHaveCount(0);
    await expect(page.getByText('460,000')).toHaveCount(0); // minimum price

    // They can prepare a sale, but only an owner or accountant posts it.
    await page.getByTestId('sell').locator('button').click();
    await expect(page.getByTestId('save-draft')).toBeVisible();
    await expect(page.getByTestId('post-sale')).toHaveCount(0);
  });
});
