/**
 * Plugin sign-in in real browsers, against a running EpicStaff with the Weather sample installed, approved, running
 * and granted. Not run in CI. See docs/plugins/how-to/local-development.md for the stack and the environment below.
 *
 *   npm --prefix plugin-sdk/test-browser ci
 *   npx --prefix plugin-sdk/test-browser playwright install chromium firefox webkit
 *   E2E_EMAIL=… E2E_PASSWORD=… E2E_ORG_A_ID=… E2E_ORG_A_NAME=… E2E_ORG_C_ID=… E2E_ORG_C_NAME=… \
 *       npm --prefix plugin-sdk/test-browser run e2e
 */
import { defineConfig } from '@playwright/test';

import { STACK } from './support/stack';

export default defineConfig({
    testDir: '.',
    testMatch: '*.spec.ts',
    // One person's sessions: tests in parallel would only make failures harder to read.
    workers: 1,
    fullyParallel: false,
    retries: 0,
    timeout: 90_000,
    expect: { timeout: 20_000 },
    reporter: 'list',
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
