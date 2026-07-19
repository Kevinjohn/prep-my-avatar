import { defineConfig, devices } from '@playwright/test';

const baseURL = `http://127.0.0.1:${process.env.E2E_PORT || '5075'}`;

export default defineConfig({
  testDir: './e2e',
  fullyParallel: false,
  workers: 1,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [['line'], ['html', { open: 'never' }]] : 'line',
  webServer: {
    command: 'node ../scripts/e2e-server.mjs',
    url: `${baseURL}/api/health/ready`,
    reuseExistingServer: false,
    timeout: 120_000,
  },
  use: {
    baseURL,
    browserName: 'chromium',
    channel: process.env.CI ? undefined : 'chrome',
    screenshot: 'only-on-failure',
    trace: 'retain-on-failure',
  },
  projects: [
    { name: 'desktop', use: { viewport: { width: 1280, height: 800 } } },
    { name: 'mobile', use: { ...devices['Pixel 7'] } },
  ],
});
