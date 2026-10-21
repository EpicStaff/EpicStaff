import { expect, test } from '@playwright/test';

import { fact, pluginFrame, signInToEpicStaff } from './support/epicstaff';
import { STACK } from './support/stack';

for (const [button, cameBackThrough] of [
    ['Connect', 'The popup’s opener'],
    ['Connect — provider severs the opener', 'The relay'],
] as const) {
    test(`inside EpicStaff: "${button}" brings the provider's answer back through ${cameBackThrough.toLowerCase()}`, async ({
        page,
    }) => {
        await signInToEpicStaff(page, STACK.orgA);
        await page.goto(`/plugins/${STACK.plugin}/connect`);
        const frame = pluginFrame(page);
        await expect(frame.getByRole('button', { name: button, exact: true })).toBeVisible();

        const popup = page.waitForEvent('popup');
        await frame.getByRole('button', { name: button, exact: true }).click();
        await popup;

        await expect(frame.getByText(`${button}: the provider answered.`)).toBeVisible({ timeout: 60_000 });
        await expect(fact(frame, 'Came back through')).toHaveText(cameBackThrough);
        await expect(fact(frame, 'code')).toHaveText(/^demo-[0-9a-f]{16}$/);
        await expect(fact(frame, 'state')).toHaveText(new RegExp(`^${STACK.orgA.id}\\.[A-Za-z0-9_-]{43}$`));
    });
}
