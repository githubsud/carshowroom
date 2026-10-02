import { defineConfig, devices } from '@playwright/test';

/**
 * E2E against the real stack: local Supabase (start it first with
 * `supabase start` and seed it with `supabase db reset`), the FastAPI
 * service and the Angular dev server. Both servers are started here unless
 * they are already running.
 */
const python = process.platform === 'win32' ? '.venv\\Scripts\\python' : '.venv/bin/python';

export default defineConfig({
  testDir: './e2e',
  fullyParallel: false,
  // One worker: the local Supabase stack is the bottleneck on developer machines.
  workers: 1,
  forbidOnly: !!process.env['CI'],
  retries: process.env['CI'] ? 1 : 0,
  reporter: process.env['CI'] ? 'github' : 'list',
  timeout: 60_000,
  // The dev server compiles lazy routes on first use; allow for a cold start.
  expect: { timeout: 15_000 },
  use: {
    baseURL: 'http://localhost:4200',
    trace: 'retain-on-failure',
    locale: 'ar-EG',
  },
  projects: [
    { name: 'setup', testMatch: /auth\.setup\.ts/ },
    {
      name: 'desktop',
      use: { ...devices['Desktop Chrome'] },
      testIgnore: /(mobile\.spec|auth\.setup)\.ts/,
      dependencies: ['setup'],
    },
    { name: 'mobile', use: { ...devices['Pixel 7'] }, testMatch: /mobile\.spec\.ts/, dependencies: ['setup'] },
  ],
  webServer: [
    {
      command: `${python} -m uvicorn app.main:create_app --factory --port 8000`,
      cwd: '../api',
      url: 'http://localhost:8000/healthz',
      reuseExistingServer: true,
      timeout: 60_000,
    },
    {
      command: 'npm start -- --port 4200',
      url: 'http://localhost:4200',
      reuseExistingServer: true,
      timeout: 180_000,
    },
  ],
});
