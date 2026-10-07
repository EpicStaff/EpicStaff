import assert from 'node:assert/strict';
import { afterEach, describe, test } from 'node:test';

import { connect, type ThemeState } from '../dist/index.js';
import { createMockHost, MOCK_DARK_THEME, MOCK_LIGHT_THEME } from '../dist/mock-host.js';
import { FakeWindow, frameWithHost, waitFor } from './helpers/fake-window.ts';

const cleanups: Array<() => void> = [];
afterEach(() => {
    while (cleanups.length > 0) cleanups.pop()?.();
});

describe('theme', () => {
    test('applies the init theme to <html> and follows theme.changed', async () => {
        const win = new FakeWindow();
        const initial: ThemeState = {
            mode: 'dark',
            tokens: { ...MOCK_DARK_THEME.tokens, '--es-color-legacy': 'red', '--not-es': 'x' } as ThemeState['tokens'],
        };
        const host = createMockHost({ theme: initial, latencyMs: 0 });
        frameWithHost(win, host);
        const bridge = await connect({ window: win.asWindow() });
        cleanups.push(() => {
            bridge.close();
            host.close();
        });
        const root = win.document.documentElement;

        assert.equal(root.style.getPropertyValue('--es-color-accent'), '#685fff');
        assert.equal(root.style.getPropertyValue('--es-color-legacy'), 'red');
        assert.equal(root.style.getPropertyValue('--not-es'), '', 'only --es-* tokens are applied');
        assert.equal(root.getAttribute('data-es-theme'), 'dark');
        assert.equal(root.style.getPropertyValue('color-scheme'), 'dark');
        assert.equal(bridge.theme.current.mode, 'dark');

        const seen: string[] = [];
        bridge.theme.onChange((theme) => seen.push(theme.mode));
        host.setTheme(MOCK_LIGHT_THEME);
        await waitFor(() => seen.length === 1);

        assert.equal(root.getAttribute('data-es-theme'), 'light');
        assert.equal(root.style.getPropertyValue('color-scheme'), 'light');
        assert.equal(root.style.getPropertyValue('--es-color-background'), '#f8fafc');
        assert.equal(
            root.style.getPropertyValue('--es-color-legacy'),
            '',
            'a token EpicStaff stopped sending is removed'
        );
        assert.equal(bridge.theme.current.mode, 'light');
    });

    test('theme: false leaves <html> alone but still tracks the theme', async () => {
        const win = new FakeWindow();
        const host = createMockHost({ latencyMs: 0 });
        frameWithHost(win, host);
        const bridge = await connect({ window: win.asWindow(), theme: false });
        cleanups.push(() => {
            bridge.close();
            host.close();
        });

        assert.equal(win.document.documentElement.getAttribute('data-es-theme'), null);
        assert.equal(bridge.theme.current.mode, 'dark');
    });
});
