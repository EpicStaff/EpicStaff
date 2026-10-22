import { expect, test } from '@playwright/test';

import {
    epicstaffPageInFrame,
    fact,
    fillLoginForm,
    historyLength,
    pluginFrame,
    pluginFrameUrl,
    signInToEpicStaff,
    signOutOfEpicStaff,
} from './support/epicstaff.ts';
import { STACK } from './support/stack.ts';

const TOKEN_ENDPOINT = '/api/auth/plugin-token/';

test('inside EpicStaff: signs in silently, shows who am I, renews, and adds no history entry', async ({ page }) => {
    await signInToEpicStaff(page, STACK.orgA);
    const before = await historyLength(page);

    await page.goto(`/plugins/${STACK.plugin}/me`);
    const frame = pluginFrame(page);

    await expect(fact(frame, 'Email')).toHaveText(STACK.email);
    await expect(fact(frame, 'Organization')).toHaveText(`${STACK.orgA.name} (${STACK.orgA.id})`);
    // Weather's Member permissions, in manifest order.
    await expect(fact(frame, 'Permissions')).toHaveText('["read","update"]');
    await expect(fact(frame, 'Context mode')).toHaveText('user');
    expect(await historyLength(page), 'only the visit itself is in the history').toBe(before + 1);

    const renewed = page.waitForResponse(
        (response) => response.url().endsWith(TOKEN_ENDPOINT) && response.status() === 200
    );
    await frame.getByRole('button', { name: 'Renew now' }).click();
    await renewed;
    await expect(fact(frame, 'Email')).toHaveText(STACK.email);
    expect(pluginFrameUrl(page)).toBe(`${STACK.pluginUrl}/me`);
    expect(await historyLength(page)).toBe(before + 1);

    await page.goBack();
    await expect(page).not.toHaveURL(/\/plugins\//);
});

test('inside EpicStaff: an interactive sign-in in the frame adds no history entry', async ({ page, context }) => {
    await signInToEpicStaff(page, STACK.orgA);
    await page.goto(`/plugins/${STACK.plugin}/me`);
    const frame = pluginFrame(page);
    await expect(fact(frame, 'Email')).toHaveText(STACK.email);
    const before = await historyLength(page);

    // EpicStaff's own page keeps working on the access token in its memory; without the refresh cookie the plugin
    // finds no EpicStaff session and has to sign in inside the frame.
    await context.clearCookies();
    await frame.getByRole('button', { name: 'Renew now' }).click();
    await frame.getByRole('button', { name: 'Sign in again' }).click();
    await expect
        .poll(() => epicstaffPageInFrame(page) ?? '')
        .toMatch(new RegExp(`^${STACK.epicstaffUrl}/plugin-login\\?continue=`));
    await fillLoginForm(frame);

    // Back through /.well-known/epicstaff/callback.html to the page it left.
    await expect(fact(frame, 'Email')).toHaveText(STACK.email);
    expect(pluginFrameUrl(page)).toBe(`${STACK.pluginUrl}/me`);
    expect(await historyLength(page), 'the sign-in replaced the frame’s page each time').toBe(before);

    await page.goBack();
    await expect(page).not.toHaveURL(/\/plugins\//);
});

test('on its own: goes to EpicStaff’s login, then the chooser, and comes back in the chosen org', async ({ page }) => {
    await page.goto(`${STACK.pluginUrl}/me`);

    await page.waitForURL((url) => url.origin === STACK.epicstaffUrl && url.pathname === '/plugin-login');
    await fillLoginForm(page);
    await page.waitForURL((url) => url.origin === STACK.epicstaffUrl && url.pathname === '/plugin-choose-org');
    await expect(page.getByRole('button', { name: STACK.orgA.name })).toBeVisible();
    await page.getByRole('button', { name: STACK.orgC.name }).click();

    await page.waitForURL(`${STACK.pluginUrl}/me`);
    await expect(fact(page, 'Organization')).toHaveText(`${STACK.orgC.name} (${STACK.orgC.id})`);
    await expect(fact(page, 'Email')).toHaveText(STACK.email);

    // The tab remembers the org: a reload signs in to it silently.
    await page.reload();
    await expect(fact(page, 'Organization')).toHaveText(`${STACK.orgC.name} (${STACK.orgC.id})`);
    expect(new URL(page.url()).origin).toBe(STACK.pluginUrl);
});

test('inside EpicStaff: after an EpicStaff logout a renewal ends the session without navigating', async ({ page }) => {
    await signInToEpicStaff(page, STACK.orgA);
    await page.goto(`/plugins/${STACK.plugin}/me`);
    const frame = pluginFrame(page);
    await expect(fact(frame, 'Email')).toHaveText(STACK.email);

    await signOutOfEpicStaff(page);
    await frame.getByRole('button', { name: 'Renew now' }).click();

    await expect(frame.getByText('Your EpicStaff session has ended.')).toBeVisible();
    await expect(frame.getByRole('button', { name: 'Sign in again' })).toBeVisible();
    expect(pluginFrameUrl(page)).toBe(`${STACK.pluginUrl}/me`);
});
