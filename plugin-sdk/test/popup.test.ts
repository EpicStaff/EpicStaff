import assert from 'node:assert/strict';
import { afterEach, describe, mock, test } from 'node:test';

import { createPluginLogin, createPopupState, type PluginLogin, PluginLoginError } from '../dist/index.js';
import { answerSilently, CODE, FakeServer, flush, json, pluginSource, until } from './helpers/fake-login.ts';
import { FakePopup, FakeWindow, type FakeWindowOptions, PLUGIN_ORIGIN } from './helpers/fake-window.ts';

const POPUP_KEY = 'epicstaff.popup.result';
const STATE = `3.${'p'.repeat(43)}`;

const cleanups: (() => void)[] = [];
afterEach(() => {
    while (cleanups.length > 0) cleanups.pop()?.();
    mock.timers.reset();
});

interface Setup {
    win: FakeWindow;
    server: FakeServer;
    login: PluginLogin;
}

function setup(windowOptions: FakeWindowOptions = {}): Setup {
    const win = new FakeWindow(windowOptions);
    const server = new FakeServer();
    const login = createPluginLogin(pluginSource(3), { window: win.asWindow(), fetch: server.fetch });
    cleanups.push(() => login.close());
    return { win, server, login };
}

async function signedIn(windowOptions: FakeWindowOptions = {}): Promise<Setup> {
    const context = setup(windowOptions);
    const started = context.login.start();
    await answerSilently(context.win, { code: CODE });
    assert.equal(await started, 'signed-in');
    return context;
}

function popupMessage(state: string, params: Record<string, string>): Record<string, unknown> {
    return { type: 'es:popup-result', protocol: 1, state, params };
}

describe('createPopupState', () => {
    test('is <org id>.<43 base64url characters>, new every time', () => {
        const first = createPopupState(3);
        assert.match(first, /^3\.[A-Za-z0-9_-]{43}$/);
        assert.notEqual(createPopupState(3), first);
        assert.match(createPopupState(2_147_483_647), /^2147483647\./);
    });

    test('refuses an id that is not a positive integer', () => {
        for (const orgId of [0, -1, 1.5, Number.NaN, 10_000_000_000]) {
            assert.throws(
                () => createPopupState(orgId),
                (error: unknown) => error instanceof PluginLoginError && error.code === 'invalid_popup_state',
                String(orgId)
            );
        }
    });
});

describe('openPopup', () => {
    test('opens the URL and resolves with the message from that popup, on this origin, with this state', async () => {
        const { win, login } = await signedIn();
        const result = login.openPopup('/api/demo-provider?state=' + STATE + '&coop=0', { state: STATE });
        const popup = win.openedPopup;

        assert.deepEqual(win.opened, [
            {
                url: `${PLUGIN_ORIGIN}/api/demo-provider?state=${STATE}&coop=0`,
                target: '_blank',
                features: 'popup,width=520,height=680',
            },
        ]);
        win.deliverMessage(popupMessage(STATE, { code: 'wrong' }), popup, 'https://evil.example');
        win.deliverMessage(popupMessage(STATE, { code: 'wrong' }), new FakePopup(), PLUGIN_ORIGIN);
        win.deliverMessage(popupMessage(`3.${'q'.repeat(43)}`, { code: 'wrong' }), popup, PLUGIN_ORIGIN);
        win.deliverMessage(
            { ...popupMessage(STATE, { code: 'wrong' }), type: 'es:login-result' },
            popup,
            PLUGIN_ORIGIN
        );
        win.deliverMessage(popupMessage(STATE, { code: 'demo-1', state: STATE }), popup, PLUGIN_ORIGIN);

        assert.deepEqual(await result, {
            via: 'opener',
            params: { code: 'demo-1', state: STATE },
            relayBody: null,
        });
        assert.equal(win.messageListenerCount, 0);
    });

    // A regression would open the address and wait for a result that never comes: fail fast instead.
    test('opens only http and https addresses', { timeout: 5000 }, async () => {
        const { win, login } = await signedIn();

        for (const url of ['javascript:alert(1)', 'data:text/html,<script>1</script>', 'blob:x', 'http://[bad']) {
            await assert.rejects(
                login.openPopup(url, { state: STATE }),
                (error: unknown) => error instanceof PluginLoginError && error.code === 'invalid_popup_url',
                url
            );
        }
        assert.equal(win.opened.length, 0, 'nothing opened');

        // Rejected with `closed` when the test cleans up.
        login.openPopup('https://accounts.example.com/o/oauth2/auth?state=x', { state: STATE }).catch(() => undefined);
        assert.equal(win.opened[0]?.url, 'https://accounts.example.com/o/oauth2/auth?state=x');
    });

    test('rejects a blocked popup and a state not made by createPopupState', async () => {
        const blocked = await signedIn({ popup: null });
        await assert.rejects(
            blocked.login.openPopup('/x', { state: STATE }),
            (error: unknown) => error instanceof PluginLoginError && error.code === 'popup_blocked'
        );

        const { win, login } = await signedIn();
        await assert.rejects(
            login.openPopup('/x', { state: 'not-a-state' }),
            (error: unknown) => error instanceof PluginLoginError && error.code === 'invalid_popup_state'
        );
        assert.deepEqual(win.opened, [], 'nothing opened');
    });

    test('polls the relay with the token every 2 seconds until it answers done', async () => {
        mock.timers.enable({ apis: ['setTimeout'] });
        const { server, login } = await signedIn();
        let polls = 0;
        server.apiResponder = () =>
            ++polls < 3
                ? json(200, { status: 'pending' })
                : json(200, { status: 'done', params: { code: 'demo-2', state: STATE } });

        const result = login.openPopup('/api/demo-provider', {
            state: STATE,
            relay: { statusPath: `/api/popup-relay/${STATE}` },
        });
        await flush();
        assert.equal(server.apiRequests.length, 0, 'the first poll waits 2 seconds');
        for (let tick = 1; tick <= 3; tick++) {
            mock.timers.tick(2000);
            await until(() => server.apiRequests.length === tick);
        }

        assert.deepEqual(await result, {
            via: 'relay',
            params: { code: 'demo-2', state: STATE },
            relayBody: { status: 'done', params: { code: 'demo-2', state: STATE } },
        });
        assert.ok(
            server.apiRequests.every(
                (request) =>
                    request.url === `${PLUGIN_ORIGIN}/api/popup-relay/${STATE}` &&
                    request.authorization === 'Bearer token-1'
            )
        );
        mock.timers.tick(10_000);
        await flush();
        assert.equal(server.apiRequests.length, 3, 'polling stopped');
    });

    test('gives up after 10 minutes and stops polling', async () => {
        mock.timers.enable({ apis: ['setTimeout'] });
        const { server, login } = await signedIn();
        server.apiResponder = () => json(200, { status: 'pending' });
        const result = login.openPopup('/api/demo-provider', {
            state: STATE,
            relay: { statusPath: `/api/popup-relay/${STATE}` },
        });
        const outcome = assert.rejects(
            result,
            (error: unknown) => error instanceof PluginLoginError && error.code === 'popup_timeout'
        );

        for (let elapsed = 0; elapsed < 600_000; elapsed += 2000) {
            mock.timers.tick(2000);
            await flush();
        }
        await outcome;
        const polls = server.apiRequests.length;
        mock.timers.tick(10_000);
        await flush();
        assert.equal(server.apiRequests.length, polls);
    });
});

describe('completePopup', () => {
    test('with an opener, posts the provider parameters to it on this origin only, and closes', async () => {
        const opener = new FakePopup();
        const { win, login } = setup({
            framed: false,
            opener,
            url: `${PLUGIN_ORIGIN}/oauth-demo/callback?code=demo-3&state=${STATE}`,
        });

        assert.deepEqual(await login.completePopup({ relayPath: '/api/popup-relay' }), { status: 'posted' });

        assert.deepEqual(opener.posted, [
            { data: popupMessage(STATE, { code: 'demo-3', state: STATE }), targetOrigin: PLUGIN_ORIGIN },
        ]);
        assert.equal(win.closedByScript, true);
    });

    test('without an opener, keeps the parameters, strips them from the address and signs in to the state’s org', async () => {
        const { win, login } = setup({
            framed: false,
            url: `${PLUGIN_ORIGIN}/oauth-demo/callback?code=demo-4&state=${STATE}#extra=1`,
        });

        assert.deepEqual(await login.completePopup({ relayPath: '/api/popup-relay' }), { status: 'signing-in' });

        assert.deepEqual(JSON.parse(win.sessionStorage.getItem(POPUP_KEY) ?? 'null'), {
            state: STATE,
            params: { code: 'demo-4', state: STATE, extra: '1' },
        });
        assert.equal(win.location.href, `${PLUGIN_ORIGIN}/oauth-demo/callback`);
        assert.equal(win.location.replacements.length, 1);
        const authorize = new URL(win.location.replacements[0] ?? '');
        assert.equal(authorize.searchParams.get('org'), '3');
        assert.equal(authorize.searchParams.has('prompt'), false);
        assert.ok(!authorize.href.includes('demo-4'), 'the provider’s parameters never go to EpicStaff');
        const pending = JSON.parse(win.sessionStorage.getItem('epicstaff.login.pending') ?? 'null') as {
            return_path: string;
        };
        assert.equal(pending.return_path, '/oauth-demo/callback');
        assert.equal(win.closedByScript, false);
    });

    test('back from the sign-in, exchanges the code, posts to the relay with the token, and closes', async () => {
        const { win, server, login } = setup({ framed: false, url: `${PLUGIN_ORIGIN}/oauth-demo/callback` });
        const saved = { state: STATE, params: { code: 'demo-5', state: STATE } };
        win.sessionStorage.setItem(POPUP_KEY, JSON.stringify(saved));
        win.sessionStorage.setItem(
            'epicstaff.login.pending',
            JSON.stringify({
                state: 'S'.repeat(43),
                code_verifier: 'v'.repeat(43),
                return_path: '/oauth-demo/callback',
                org: 3,
                created_at: Date.now(),
            })
        );
        win.sessionStorage.setItem('epicstaff.login.result', JSON.stringify({ state: 'S'.repeat(43), code: CODE }));
        server.apiResponder = () => new Response(null, { status: 204 });

        assert.deepEqual(await login.completePopup({ relayPath: '/api/popup-relay' }), { status: 'relayed' });

        const [relay] = server.apiRequests;
        assert.equal(relay?.url, `${PLUGIN_ORIGIN}/api/popup-relay`);
        assert.equal(relay?.init.method, 'POST');
        assert.equal(relay?.authorization, 'Bearer token-1');
        assert.deepEqual(JSON.parse(String(relay?.init.body)), saved);
        assert.equal(win.sessionStorage.getItem(POPUP_KEY), null);
        assert.equal(win.closedByScript, true);
        assert.equal(win.document.frames.length, 0, 'no silent attempt');
    });

    test('keeps the parameters when the relay refuses them, so a reload can try again', async () => {
        const { win, server, login } = setup({ framed: false, url: `${PLUGIN_ORIGIN}/oauth-demo/callback` });
        win.sessionStorage.setItem(POPUP_KEY, JSON.stringify({ state: STATE, params: { code: 'x', state: STATE } }));
        win.sessionStorage.setItem(
            'epicstaff.login.pending',
            JSON.stringify({
                state: 'S'.repeat(43),
                code_verifier: 'v'.repeat(43),
                return_path: '/oauth-demo/callback',
                org: 3,
                created_at: Date.now(),
            })
        );
        win.sessionStorage.setItem('epicstaff.login.result', JSON.stringify({ state: 'S'.repeat(43), code: CODE }));
        server.apiResponder = () => json(403, { code: 'state_mismatch' });

        const outcome = await login.completePopup({ relayPath: '/api/popup-relay' });

        assert.equal(outcome.status, 'failed');
        assert.equal(outcome.status === 'failed' ? outcome.error.code : null, 'relay_failed');
        assert.notEqual(win.sessionStorage.getItem(POPUP_KEY), null);
        assert.equal(win.closedByScript, false);
    });

    test('without an opener or a relay, or without a valid state, hands nothing on', async () => {
        const noRelay = setup({ framed: false, url: `${PLUGIN_ORIGIN}/cb?code=x&state=${STATE}` });
        assert.deepEqual(await noRelay.login.completePopup(), { status: 'no-opener' });

        const badState = setup({ framed: false, url: `${PLUGIN_ORIGIN}/cb?code=x&state=nope` });
        assert.deepEqual(await badState.login.completePopup({ relayPath: '/api/popup-relay' }), { status: 'invalid' });
        assert.deepEqual(badState.win.location.replacements, []);

        const nothing = setup({ framed: false, url: `${PLUGIN_ORIGIN}/cb` });
        assert.deepEqual(await nothing.login.completePopup({ relayPath: '/api/popup-relay' }), { status: 'invalid' });
    });
});
