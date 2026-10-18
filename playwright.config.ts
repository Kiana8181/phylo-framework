import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
  testDir: './tests/browser',
  globalSetup: './tests/browser/global-setup.ts',
  fullyParallel: false,
  workers: 1,
  forbidOnly: !!process.env.CI,
  retries: 0,
  timeout: 180_000,
  expect: {timeout: 20_000},
  outputDir: 'test-results/browser',
  reporter: [['list'], ['html', {outputFolder: 'coverage/browser', open: 'never'}],
    ['junit', {outputFile: 'coverage/browser/junit.xml'}]],
  use: {baseURL: 'http://127.0.0.1:53000', trace: 'retain-on-failure', screenshot: 'only-on-failure'},
  projects: [{name: 'chromium', use: {...devices['Desktop Chrome']}}],
  webServer: {
    command: 'npm -w @phylo/contracts run build && npm -w web run dev -- --hostname 127.0.0.1 --port 53000',
    url: 'http://127.0.0.1:53000/auth',
    env: {NEXT_PUBLIC_API_BASE_URL: 'http://127.0.0.1:58000', NEXT_TELEMETRY_DISABLED: '1', TEST_BROWSER_COVERAGE: '1'},
    reuseExistingServer: false,
    timeout: 180_000,
  },
});
