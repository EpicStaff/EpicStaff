import { expect, type FrameLocator, type Page } from '@playwright/test';

import { type Organization, STACK } from './stack';

/** Makes `org` EpicStaff's active organization on every EpicStaff page this test loads. */
export async function useOrganization(page: Page, org: Organization): Promise<void> {
    await page.addInitScript(
        ({ origin, orgId }) => {
            if (location.origin === origin) localStorage.setItem('epicstaff.activeOrgId', String(orgId));
        },
        { origin: STACK.epicstaffUrl, orgId: org.id }
    );
}

/**
 * Fills EpicStaff's login form, wherever it is shown (`/login`, or `/plugin-login` top-level or inside the plugin's
 * frame), and submits it.
 */
export async function fillLoginForm(scope: Page | FrameLocator): Promise<void> {
    await scope.getByPlaceholder('example@gmail.com').fill(STACK.email);
    const password = scope.getByPlaceholder('Enter password');
    await password.fill(STACK.password);
    await password.press('Enter');
}

/** Signs in to EpicStaff at `/login`, in `org`. */
export async function signInToEpicStaff(page: Page, org: Organization): Promise<void> {
    await useOrganization(page, org);
    await page.goto('/login');
    await fillLoginForm(page);
    await page.waitForURL((url) => url.origin === STACK.epicstaffUrl && !url.pathname.startsWith('/login'));
}

/** Ends the EpicStaff session the way the app's own logout does: refresh from the cookie, then log out. */
export async function signOutOfEpicStaff(page: Page): Promise<void> {
    const refreshed = await page.request.post(`${STACK.epicstaffUrl}/api/auth/refresh/`);
    expect(refreshed.ok()).toBe(true);
    const { access } = (await refreshed.json()) as { access: string };
    const loggedOut = await page.request.post(`${STACK.epicstaffUrl}/api/auth/logout/`, {
        headers: { authorization: `Bearer ${access}` },
    });
    expect(loggedOut.ok()).toBe(true);
}

/** The plugin's frame on EpicStaff's plugin page. */
export function pluginFrame(page: Page): FrameLocator {
    return page.frameLocator('iframe.plugin-host__frame');
}

/** The current address of the plugin's frame. */
export function pluginFrameUrl(page: Page): string | undefined {
    return page
        .frames()
        .map((frame) => frame.url())
        .find((url) => url.startsWith(STACK.pluginUrl));
}

/** The address of the plugin's frame while it shows one of EpicStaff's pages (the sign-in), if it does. */
export function epicstaffPageInFrame(page: Page): string | undefined {
    return page
        .frames()
        .filter((frame) => frame !== page.mainFrame())
        .map((frame) => frame.url())
        .find((url) => url.startsWith(STACK.epicstaffUrl));
}

export function historyLength(page: Page): Promise<number> {
    return page.evaluate(() => history.length);
}

/** The value next to a label in one of the sample's fact lists. */
export function fact(scope: FrameLocator | Page, label: string) {
    return scope.locator(`dt:text-is("${label}") + dd`);
}
