/**
 * Plugin sign-in in real browsers, against a running EpicStaff with the Weather sample installed, approved, running
 * and granted. `.github/scripts/plugin_platform_e2e.sh` runs it on a fresh stack, locally and in CI; see
 * docs/plugins/how-to/local-development.md.
 *
 *   npm --prefix plugin-sdk/test-browser ci
 *   npx --prefix plugin-sdk/test-browser playwright install chromium firefox webkit
 *   E2E_PACKAGE=… E2E_SUPERADMIN_EMAIL=… E2E_SUPERADMIN_PASSWORD=… npm --prefix plugin-sdk/test-browser run e2e:seed
 *   npm --prefix plugin-sdk/test-browser run e2e
 *
 * The checks read the stack file the seed wrote (E2E_STACK_FILE, default .stack.json here). E2E_EMAIL, E2E_PASSWORD,
 * E2E_ORG_A_ID, E2E_ORG_A_NAME, E2E_ORG_C_ID and E2E_ORG_C_NAME, when set, win over it.
 *
 * With CI set: a test.only fails the run, and the HTML report goes to playwright-report/. Traces are kept for failed
 * tests. Never retried: a flaky test gets fixed.
 */
import { defineConfig } from '@playwright/test';

import { STACK } from './support/stack.ts';

const inCi = Boolean(process.env['CI']);

export default defineConfig({
    testDir: '.',
    testMatch: '*.spec.ts',
    // One person's sessions: tests in parallel would only make failures harder to read.
    workers: 1,
    fullyParallel: false,
    forbidOnly: inCi,
    retries: 0,
    timeout: 90_000,
    expect: { timeout: 20_000 },
    reporter: inCi ? [['list'], ['html', { outputFolder: 'playwright-report', open: 'never' }]] : 'list',
    use: {
        baseURL: STACK.epicstaffUrl,
        // A local wildcard certificate on the HTTPS stack.
        ignoreHTTPSErrors: true,
        trace: 'retain-on-failure',
    },
    projects: [
        { name: 'chromium', use: { browserName: 'chromium' } },
        { name: 'firefox', use: { browserName: 'firefox' } },
        { name: 'webkit', use: { browserName: 'webkit' } },
    ],
});
