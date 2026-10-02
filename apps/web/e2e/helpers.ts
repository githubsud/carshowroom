import { expect, Page } from '@playwright/test';

export const PASSWORD = 'Demo-Pass-2026';
export const NOUR = '11111111-1111-1111-1111-111111111111';
export const DOHA = '22222222-2222-2222-2222-222222222222';

export async function login(page: Page, email: string, password = PASSWORD): Promise<void> {
  await page.goto('/login');
  await page.locator('#email').fill(email);
  await page.locator('#password').fill(password);
  await page.getByTestId('login-submit').locator('button').click();
}

export async function expectDirection(page: Page, lang: 'ar' | 'en'): Promise<void> {
  await expect(page.locator('html')).toHaveAttribute('lang', lang);
  await expect(page.locator('html')).toHaveAttribute('dir', lang === 'ar' ? 'rtl' : 'ltr');
}

/** Saved sessions written by auth.setup.ts. */
export const AS_OWNER = 'e2e/.auth/owner.json';
export const AS_PARTNER = 'e2e/.auth/partner.json';
export const AS_SALES = 'e2e/.auth/sales.json';
export const AS_ACCOUNTANT = 'e2e/.auth/accountant.json';

/** "1,234.50 ج.م" / "EGP -10.00" -> 1234.5 (test arithmetic only; the app never does this). */
export function amountOf(text: string | null): number {
  const match = /-?[\d,]+(?:\.\d+)?/.exec(text ?? '');
  return match ? Number(match[0].replace(/,/g, '')) : Number.NaN;
}
