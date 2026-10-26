import assert from 'node:assert/strict';
import { afterEach, describe, test } from 'node:test';

import { applyTheme, type EpicStaffPlugin, startPlugin, type ThemeState } from '../dist/index.js';
import { closeFakeHosts, configFetch, FakeWindow, frameWithHost, waitFor } from './helpers/fake-window.ts';

const cleanups: (() => void)[] = [];
afterEach(() => {
    while (cleanups.length > 0) cleanups.pop()?.();
    closeFakeHosts();
});

async function start(win: FakeWindow, applyThemeToPage = true): Promise<EpicStaffPlugin> {
    const plugin = await startPlugin({ window: win.asWindow(), fetch: configFetch(), applyTheme: applyThemeToPage });
    cleanups.push(() => plugin.close());
    return plugin;
}

describe('theme', () => {
    test('applies --es-* tokens, data-es-theme and color-scheme to <html>, and removes stale tokens', () => {
        const win = new FakeWindow();
        const document = win.asWindow().document;
        const root = win.document.documentElement;

        applyTheme(document, {
            mode: 'dark',
            tokens: { '--es-color-accent': '#685fff', '--es-color-legacy': 'red', '--not-es': 'x' },
        } as ThemeState);
        assert.equal(root.style.getPropertyValue('--es-color-accent'), '#685fff');
        assert.equal(root.style.getPropertyValue('--not-es'), '', 'only --es-* tokens');
        assert.equal(root.getAttribute('data-es-theme'), 'dark');
        assert.equal(root.style.getPropertyValue('color-scheme'), 'dark');

        applyTheme(document, { mode: 'light', tokens: { '--es-color-accent': '#5b52f0' } });
        assert.equal(root.style.getPropertyValue('--es-color-accent'), '#5b52f0');
        assert.equal(root.style.getPropertyValue('--es-color-legacy'), '', 'a token no longer sent is removed');
        assert.equal(root.getAttribute('data-es-theme'), 'light');
        assert.equal(root.style.getPropertyValue('color-scheme'), 'light');
    });

    test('applies the es:init theme and follows theme.changed', async () => {
        const win = new FakeWindow();
        const host = frameWithHost(win);
        const plugin = await start(win);
        const root = win.document.documentElement;
        const seen: string[] = [];
        plugin.onThemeChange((theme) => seen.push(theme.mode));

        assert.equal(root.style.getPropertyValue('--es-color-accent'), '#685fff');
        assert.equal(plugin.theme()?.mode, 'dark');

        host.port().postMessage({
            type: 'theme.changed',
            theme: { mode: 'light', tokens: { '--es-color-background': '#f8fafc' } },
        });
        await waitFor(() => seen.length === 1);

        assert.equal(root.getAttribute('data-es-theme'), 'light');
        assert.equal(root.style.getPropertyValue('--es-color-background'), '#f8fafc');
        assert.equal(root.style.getPropertyValue('--es-color-accent'), '');
        assert.equal(plugin.theme()?.mode, 'light');
    });

    test('applyTheme: false leaves <html> alone but still tracks the theme', async () => {
        const win = new FakeWindow();
        frameWithHost(win);
        const plugin = await start(win, false);

        assert.equal(win.document.documentElement.getAttribute('data-es-theme'), null);
        assert.equal(plugin.theme()?.mode, 'dark');
    });
});
