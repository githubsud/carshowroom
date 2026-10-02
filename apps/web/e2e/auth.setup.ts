import { expect, test as setup } from '@playwright/test';

import { login } from './helpers';

/**
 * Sign each demo role in once and save the browser session, so most tests
 * start already signed in (fewer Auth round-trips, faster and steadier runs).
 */
const USERS = {
  owner: { email: 'owner@nour.example', landing: /\/t\/[^/]+\/dashboard$/ },
  partner: { email: 'partner@nour.example', landing: /\/tenants$/ },
  sales: { email: 'sales@nour.example', landing: /\/t\/[^/]+\/dashboard$/ },
  accountant: { email: 'accountant@nour.example', landing: /\/t\/[^/]+\/dashboard$/ },
} as const;

for (const [role, user] of Object.entries(USERS)) {
  setup(`sign in as ${role}`, async ({ page }) => {
    await login(page, user.email);
    await expect(page).toHaveURL(user.landing);
    await page.context().storageState({ path: `e2e/.auth/${role}.json` });
  });
}
