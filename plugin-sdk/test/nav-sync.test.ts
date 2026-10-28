import assert from 'node:assert/strict';
import { afterEach, describe, test } from 'node:test';

import { type EpicStaffPlugin, startPlugin, type StartPluginOptions } from '../dist/index.js';
import {
    closeFakeHosts,
    configFetch,
    delay,
    FakeWindow,
    frameWithHost,
    PLUGIN_ORIGIN,
    waitFor,
} from './helpers/fake-window.ts';

const cleanups: (() => void)[] = [];
afterEach(() => {
    while (cleanups.length > 0) cleanups.pop()?.();
    closeFakeHosts();
});

async function start(win: FakeWindow, options: StartPluginOptions = {}): Promise<EpicStaffPlugin> {
    const plugin = await startPlugin({ window: win.asWindow(), fetch: configFetch(), ...options });
    cleanups.push(() => plugin.close());
    return plugin;
}

describe('nav sync, pathname routing', () => {
    test('turns pushState into replaceState and reports {replace: false}', async () => {
        const win = new FakeWindow();
        const host = frameWithHost(win);
        await start(win);

        win.history.pushState({ id: 2 }, '', '/forecast?city=Paris');

        assert.equal(win.location.pathname, '/forecast');
        assert.equal(win.history.length, 1, 'no entry is added to the frame history');
        assert.deepEqual(
            win.history.calls.map((call) => call.method),
            ['replaceState']
        );
        await waitFor(() => host.received.length === 1);
        assert.deepEqual(host.received, [{ type: 'nav.changed', path: '/forecast?city=Paris', replace: false }]);
    });

    test('reports replaceState with {replace: true}, and never the path EpicStaff already shows', async () => {
        const win = new FakeWindow();
        const host = frameWithHost(win);
        await start(win);

        win.history.replaceState(null, '', '/about');
        win.history.replaceState({ id: 3 }, '', '/about');
        win.history.pushState(null, '', '/about');

        await delay(20);
        assert.deepEqual(host.received, [{ type: 'nav.changed', path: '/about', replace: true }]);
    });

    test('nav.navigate moves the page, fires popstate, and is not echoed back', async () => {
        const win = new FakeWindow();
        const host = frameWithHost(win);
        await start(win);
        let popstates = 0;
        win.addEventListener('popstate', () => {
            popstates++;
            // What a router does on popstate: render, then write the same address back.
            win.history.replaceState({ id: 9 }, '', '/about');
        });

        host.port().postMessage({ type: 'nav.navigate', path: '/about' });
        await waitFor(() => popstates === 1);

        assert.equal(win.location.href, `${PLUGIN_ORIGIN}/about`);
        assert.ok(!win.dispatched.includes('hashchange'));
        await delay(20);
        assert.deepEqual(host.received, [], 'the router writing the same address is not reported');
    });

    test("moves the page to EpicStaff's path when it did not start on it", async () => {
        const win = new FakeWindow({ url: `${PLUGIN_ORIGIN}/` });
        const host = frameWithHost(win, { init: { nav: { path: '/about' } } });
        await start(win);

        assert.equal(win.location.pathname, '/about');
        await delay(20);
        assert.deepEqual(host.received, []);
    });

    test('ignores an invalid nav.navigate and unknown message types', async () => {
        const win = new FakeWindow({ url: `${PLUGIN_ORIGIN}/about` });
        const host = frameWithHost(win, { init: { nav: { path: '/about' } } });
        await start(win);

        host.port().postMessage({ type: 'nav.navigate', path: '/../admin' });
        host.port().postMessage({ type: 'something.new', path: '/x' });
        await delay(20);

        assert.equal(win.location.pathname, '/about');
    });

    test('a custom onNavigate replaces the default handling', async () => {
        const win = new FakeWindow();
        const host = frameWithHost(win);
        const routed: string[] = [];
        await start(win, { onNavigate: (path) => routed.push(path) });

        host.port().postMessage({ type: 'nav.navigate', path: '/about' });
        await waitFor(() => routed.length === 1);

        assert.deepEqual(routed, ['/about']);
        assert.equal(win.location.pathname, '/');
        assert.deepEqual(win.dispatched, []);
    });

    test('close() restores history.pushState and history.replaceState', async () => {
        const win = new FakeWindow();
        frameWithHost(win);
        const plugin = await start(win);
        assert.equal(Object.hasOwn(win.history, 'pushState'), true);

        plugin.close();

        assert.equal(Object.hasOwn(win.history, 'pushState'), false);
        assert.equal(Object.hasOwn(win.history, 'replaceState'), false);
    });
});

describe('nav sync, hash routing', () => {
    test('reports hash routes and fires hashchange on nav.navigate', async () => {
        const win = new FakeWindow({ url: `${PLUGIN_ORIGIN}/#/` });
        const host = frameWithHost(win);
        await start(win, { routing: 'hash' });

        win.history.pushState(null, '', '#/forecast?city=New York');
        await waitFor(() => host.received.length === 1);
        assert.deepEqual(host.received, [{ type: 'nav.changed', path: '/forecast?city=New%20York', replace: false }]);

        host.port().postMessage({ type: 'nav.navigate', path: '/about' });
        await waitFor(() => win.dispatched.includes('hashchange'));
        assert.equal(win.location.hash, '#/about');
        assert.deepEqual(win.dispatched, ['popstate', 'hashchange']);
    });
});

describe('nav sync before the handshake', () => {
    test('queues route changes made before EpicStaff answered; the latest wins', async () => {
        const win = new FakeWindow();
        const host = frameWithHost(win);
        const starting = start(win);

        // The router's first navigation and a redirect, while the config loads.
        win.history.replaceState(null, '', '/forecast');
        win.history.replaceState(null, '', '/forecast?city=Berlin');
        await starting;

        await waitFor(() => host.received.length === 1);
        await delay(20);
        assert.deepEqual(host.received, [{ type: 'nav.changed', path: '/forecast?city=Berlin', replace: true }]);
    });

    test('holds reports over the rate back instead of sending them', async () => {
        const win = new FakeWindow();
        const host = frameWithHost(win);
        await start(win);

        for (let index = 0; index < 115; index++) win.history.pushState(null, '', `/page/${index}`);

        await waitFor(() => host.received.length === 110);
        await delay(20);
        assert.equal(host.received.length, 110, 'stays under the 120 per minute EpicStaff accepts');
    });
});
