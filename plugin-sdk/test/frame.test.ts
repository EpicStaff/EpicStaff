import assert from 'node:assert/strict';
import { afterEach, describe, test } from 'node:test';

import { type EpicStaffPlugin, performHandshake, startPlugin, takeOrgHint } from '../dist/index.js';
import {
    closeFakeHosts,
    configFetch,
    EPICSTAFF_ORIGIN,
    FakeWindow,
    frameWithHost,
    type FakeHostOptions,
    PLUGIN_ORIGIN,
} from './helpers/fake-window.ts';

const cleanups: (() => void)[] = [];
afterEach(() => {
    while (cleanups.length > 0) cleanups.pop()?.();
    closeFakeHosts();
});

async function start(win: FakeWindow, initTimeoutMs = 3000): Promise<EpicStaffPlugin> {
    const plugin = await startPlugin({ window: win.asWindow(), fetch: configFetch(), initTimeoutMs });
    cleanups.push(() => plugin.close());
    return plugin;
}

async function handshake(options: FakeHostOptions, timeoutMs = 50): ReturnType<typeof performHandshake> {
    const win = new FakeWindow();
    frameWithHost(win, options);
    return performHandshake(win.asWindow(), { epicstaffOrigin: EPICSTAFF_ORIGIN, timeoutMs });
}

describe('frame handshake', () => {
    test('posts es:ready to EpicStaff origin only, and takes es:init with its port', async () => {
        const win = new FakeWindow();
        frameWithHost(win, { init: { nav: { path: '/about' } } });

        const plugin = await start(win);

        assert.deepEqual(win.parentFrame.posted, [
            { data: { type: 'es:ready', protocol: 1 }, targetOrigin: EPICSTAFF_ORIGIN },
        ]);
        assert.equal(plugin.framed, true);
        assert.deepEqual(plugin.org, { id: 3, name: 'Acme' });
        assert.equal(win.messageListenerCount, 0, 'the handshake listener is gone');
    });

    test('ignores es:init from another origin', async () => {
        assert.deepEqual(await handshake({ origin: 'https://evil.example' }), { framed: false, reason: 'timeout' });
    });

    test('ignores es:init whose source is not window.parent', async () => {
        assert.deepEqual(await handshake({ source: {} }), { framed: false, reason: 'timeout' });
    });

    test('runs unframed on es:error', async () => {
        assert.deepEqual(await handshake({ error: 'unsupported_protocol' }), {
            framed: false,
            reason: 'unsupported_protocol',
        });
    });

    test('runs unframed when nobody answers in time, and never posts outside a frame', async () => {
        const silent = new FakeWindow();
        frameWithHost(silent, { silent: true });
        const unanswered = await start(silent, 20);
        assert.equal(unanswered.framed, false);
        assert.equal(unanswered.unframedReason, 'timeout');
        assert.equal(Object.hasOwn(silent.history, 'pushState'), false, 'history is restored');

        const topLevel = new FakeWindow({ framed: false });
        const alone = await start(topLevel);
        assert.equal(alone.unframedReason, 'not_framed');
    });

    test('a malformed init still connects with safe defaults', async () => {
        const win = new FakeWindow();
        frameWithHost(win, { init: { theme: 'x', nav: { path: '/../admin' }, org: { id: -1, name: 'x' } } });

        const plugin = await start(win);

        assert.equal(plugin.framed, true);
        assert.equal(plugin.org, null);
        assert.deepEqual(plugin.theme(), { mode: 'dark', tokens: {} });
    });
});

describe('organization hint', () => {
    test('removes es_org from the address, keeping the rest exactly as written', () => {
        const win = new FakeWindow({ url: `${PLUGIN_ORIGIN}/forecast?city=New%20York&es_org=3#top` });

        assert.equal(takeOrgHint(win.asWindow()), 3);
        assert.equal(win.location.href, `${PLUGIN_ORIGIN}/forecast?city=New%20York#top`);
        assert.deepEqual(
            win.history.calls.map((call) => call.method),
            ['replaceState']
        );
    });

    test('takes the last es_org, the one EpicStaff appended, and refuses a non-id', () => {
        const repeated = new FakeWindow({ url: `${PLUGIN_ORIGIN}/?es_org=9&es_org=4` });
        assert.equal(takeOrgHint(repeated.asWindow()), 4);
        assert.equal(repeated.location.href, `${PLUGIN_ORIGIN}/`);

        const invalid = new FakeWindow({ url: `${PLUGIN_ORIGIN}/?es_org=1e3` });
        assert.equal(takeOrgHint(invalid.asWindow()), null);
        assert.equal(invalid.location.href, `${PLUGIN_ORIGIN}/`);
    });

    test('leaves an address without a hint untouched', () => {
        const win = new FakeWindow({ url: `${PLUGIN_ORIGIN}/about?x=1` });
        assert.equal(takeOrgHint(win.asWindow()), null);
        assert.deepEqual(win.history.calls, []);
    });

    test('startPlugin keeps the hint even unframed', async () => {
        const win = new FakeWindow({ framed: false, url: `${PLUGIN_ORIGIN}/?es_org=12` });
        const plugin = await start(win);
        assert.equal(plugin.orgHint, 12);
    });
});
