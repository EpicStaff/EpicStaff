import assert from 'node:assert/strict';
import { afterEach, describe, mock, test } from 'node:test';

import { createPluginLogin, type PluginLogin, PluginLoginError } from '../dist/index.js';
import { codeChallengeFor, createPkcePair } from '../dist/pkce.js';
import {
    answerSilently,
    AUTHORIZE_URL,
    CODE,
    FakeServer,
    flush,
    gatewayDeny,
    json,
    nextSilentFrame,
    OTHER_CODE,
    pluginSource,
    postFromFrame,
    tokenBody,
    until,
} from './helpers/fake-login.ts';
import { EPICSTAFF_ORIGIN, FakeWindow, type FakeWindowOptions, PLUGIN_ORIGIN } from './helpers/fake-window.ts';

const PENDING = 'epicstaff.login.pending';
const RESULT = 'epicstaff.login.result';
const STATE = 'S'.repeat(43);

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

function setup(windowOptions: FakeWindowOptions = {}, orgHint: number | null = 3): Setup {
    const win = new FakeWindow({ url: `${PLUGIN_ORIGIN}/me?x=1#top`, ...windowOptions });
    const server = new FakeServer();
    const login = createPluginLogin(pluginSource(orgHint), { window: win.asWindow(), fetch: server.fetch });
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

function storedPending(win: FakeWindow): Record<string, unknown> {
    return JSON.parse(win.sessionStorage.getItem(PENDING) ?? 'null') as Record<string, unknown>;
}

describe('createPluginLogin', () => {
    test('refuses a page that is not a secure context, or has no Web Crypto', () => {
        for (const options of [{ secure: false }, { crypto: null }]) {
            const win = new FakeWindow(options);
            assert.throws(
                () => createPluginLogin(pluginSource(), { window: win.asWindow() }),
                (error: unknown) => error instanceof PluginLoginError && error.code === 'insecure_context'
            );
        }
    });

    test('refuses a plugin whose platform config offers no login', () => {
        const source = pluginSource();
        const win = new FakeWindow();
        assert.throws(
            () =>
                createPluginLogin({ ...source, config: { ...source.config, login: null } }, { window: win.asWindow() }),
            (error: unknown) => error instanceof PluginLoginError && error.code === 'login_unavailable'
        );
    });
});

describe('PKCE', () => {
    test('matches the RFC 7636 appendix B vector', async () => {
        assert.equal(
            await codeChallengeFor(crypto, 'dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk'),
            'E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM'
        );
    });

    test('makes a 43-character verifier and its S256 challenge', async () => {
        const pair = await createPkcePair(crypto);
        assert.match(pair.verifier, /^[A-Za-z0-9_-]{43}$/);
        assert.equal(pair.challenge, await codeChallengeFor(crypto, pair.verifier));
    });
});

describe('silent sign-in at start', () => {
    test('loads authorize with exactly the pinned parameters and prompt=none in a hidden frame', async () => {
        const { win, login } = setup();
        void login.start();

        const { frame, url, state } = await nextSilentFrame(win);

        assert.equal(`${url.origin}${url.pathname}`, AUTHORIZE_URL);
        assert.deepEqual(
            [...url.searchParams.keys()],
            ['plugin', 'state', 'code_challenge', 'code_challenge_method', 'org', 'prompt']
        );
        assert.equal(url.searchParams.get('plugin'), 'weather');
        assert.match(state, /^[A-Za-z0-9_-]{43,128}$/);
        assert.match(url.searchParams.get('code_challenge') ?? '', /^[A-Za-z0-9_-]{43}$/);
        assert.equal(url.searchParams.get('code_challenge_method'), 'S256');
        assert.equal(url.searchParams.get('org'), '3');
        assert.equal(url.searchParams.get('prompt'), 'none');
        assert.equal(frame.hidden, true);
        assert.equal(frame.style['display'], 'none');
        assert.equal(login.state, 'signing-in');
    });

    test('sends no org without a hint', async () => {
        const { win, login } = setup({}, null);
        void login.start();

        const { url } = await nextSilentFrame(win);

        assert.equal(url.searchParams.has('org'), false);
    });

    test('exchanges a code with credentials omitted and JSON, binding the verifier to the challenge', async () => {
        const { win, server, login } = setup();
        const changes: string[] = [];
        login.onChange((state) => changes.push(state));
        const started = login.start();

        const silent = await answerSilently(win, { code: CODE });

        assert.equal(await started, 'signed-in');
        const [exchange] = server.tokenRequests;
        assert.ok(exchange);
        assert.equal(exchange.init.method, 'POST');
        assert.equal(exchange.init.credentials, 'omit');
        assert.equal(new Headers(exchange.init.headers).get('content-type'), 'application/json');
        const body = JSON.parse(String(exchange.init.body)) as { code: string; code_verifier: string };
        assert.deepEqual(Object.keys(body), ['code', 'code_verifier']);
        assert.equal(body.code, CODE);
        assert.equal(await codeChallengeFor(crypto, body.code_verifier), silent.url.searchParams.get('code_challenge'));
        assert.equal(silent.frame.removed, true, 'the hidden frame is gone');
        assert.deepEqual(win.location.replacements, [], 'no navigation at all');
        assert.deepEqual(changes, ['signing-in', 'signed-in']);
        assert.deepEqual(
            { ...login.session, expiresAt: 0 },
            {
                plugin: { identifier: 'weather', version: '0.3.0' },
                org: { id: 3, name: 'Acme' },
                user: { id: 42, email: 'ada@acme.test', name: 'Ada' },
                permissions: ['read'],
                expiresAt: 0,
            }
        );
        assert.ok(Math.abs((login.session?.expiresAt ?? 0) - (Date.now() + 900_000)) < 5000);
    });

    test('keeps the token in memory only: storage holds just the org id', async () => {
        const { win } = await signedIn();

        assert.deepEqual([...win.sessionStorage.items.entries()], [['epicstaff.login.org', '3']]);
        assert.ok(![...win.sessionStorage.items.values()].some((value) => value.includes('token-1')));
    });

    test('ignores messages from another origin, another source or with another state', async () => {
        const { win, server, login } = setup();
        const started = login.start();
        const silent = await nextSilentFrame(win);
        const message = { type: 'es:login-result', protocol: 1, state: silent.state, code: CODE };

        win.deliverMessage(message, silent.frame.contentWindow, EPICSTAFF_ORIGIN);
        win.deliverMessage(message, {}, PLUGIN_ORIGIN);
        win.deliverMessage({ ...message, state: STATE }, silent.frame.contentWindow, PLUGIN_ORIGIN);
        win.deliverMessage({ ...message, type: 'es:popup-result' }, silent.frame.contentWindow, PLUGIN_ORIGIN);
        await flush();
        assert.equal(server.tokenRequests.length, 0);
        assert.equal(silent.frame.removed, false);

        postFromFrame(win, silent, { code: OTHER_CODE });
        assert.equal(await started, 'signed-in');
        assert.equal(server.tokenRequests.length, 1);
    });

    test('counts no answer within 10 seconds as login_required, and then signs in interactively', async () => {
        mock.timers.enable({ apis: ['setTimeout'] });
        const { win, login } = setup();
        const started = login.start();
        const silent = await nextSilentFrame(win);

        mock.timers.tick(9_999);
        await flush();
        assert.equal(silent.frame.removed, false);
        mock.timers.tick(1);

        assert.equal(await started, 'signing-in');
        assert.equal(silent.frame.removed, true);
        assert.equal(win.location.replacements.length, 1);
    });

    test('access_denied ends in the access-denied state, without navigating', async () => {
        const { win, login } = setup();
        const started = login.start();

        await answerSilently(win, { error: 'access_denied' });

        assert.equal(await started, 'access-denied');
        assert.deepEqual(win.location.replacements, []);
        assert.equal(login.session, null);
    });
});

describe('interactive sign-in', () => {
    for (const error of ['login_required', 'interaction_required']) {
        test(`${error} replaces the page with authorize (never assign), keeping the pending sign-in`, async () => {
            const { win, login } = setup();
            const started = login.start();

            await answerSilently(win, { error });

            assert.equal(await started, 'signing-in');
            assert.deepEqual(win.location.assignments, []);
            assert.equal(win.location.replacements.length, 1);
            const url = new URL(win.location.replacements[0] ?? '');
            assert.equal(`${url.origin}${url.pathname}`, AUTHORIZE_URL);
            assert.deepEqual(
                [...url.searchParams.keys()],
                ['plugin', 'state', 'code_challenge', 'code_challenge_method', 'org']
            );
            const pending = storedPending(win);
            assert.deepEqual(Object.keys(pending).sort(), [
                'code_verifier',
                'created_at',
                'org',
                'return_path',
                'state',
            ]);
            assert.equal(pending['state'], url.searchParams.get('state'));
            assert.equal(pending['return_path'], '/me?x=1#top');
            assert.equal(pending['org'], 3);
            assert.equal(
                await codeChallengeFor(crypto, String(pending['code_verifier'])),
                url.searchParams.get('code_challenge')
            );
        });
    }

    test('a return path that is not a plain own path becomes /', async () => {
        const { win, login } = setup({ url: `${PLUGIN_ORIGIN}/caf%C3%A9?q=${'x'.repeat(2100)}` });
        const started = login.start();
        await answerSilently(win, { error: 'login_required' });
        await started;

        assert.equal(storedPending(win)['return_path'], '/');
    });

    test('start finishes a sign-in that came back: no frame, the code exchanged, both entries removed', async () => {
        const verifier = 'v'.repeat(43);
        const { win, server, login } = setup();
        win.sessionStorage.setItem(
            PENDING,
            JSON.stringify({
                state: STATE,
                code_verifier: verifier,
                return_path: '/me',
                org: 3,
                created_at: Date.now(),
            })
        );
        win.sessionStorage.setItem(RESULT, JSON.stringify({ state: STATE, code: CODE }));

        assert.equal(await login.start(), 'signed-in');

        assert.equal(win.document.frames.length, 0);
        assert.deepEqual(JSON.parse(String(server.tokenRequests[0]?.init.body)), {
            code: CODE,
            code_verifier: verifier,
        });
        assert.equal(win.sessionStorage.getItem(PENDING), null);
        assert.equal(win.sessionStorage.getItem(RESULT), null);
    });

    test('a result whose state does not match the pending sign-in is dropped, and start signs in silently', async () => {
        const { win, server, login } = setup();
        win.sessionStorage.setItem(
            PENDING,
            JSON.stringify({
                state: STATE,
                code_verifier: 'v'.repeat(43),
                return_path: '/',
                org: 3,
                created_at: Date.now(),
            })
        );
        win.sessionStorage.setItem(RESULT, JSON.stringify({ state: 'T'.repeat(43), code: CODE }));
        void login.start();

        await nextSilentFrame(win);

        assert.equal(server.tokenRequests.length, 0);
        assert.equal(win.sessionStorage.getItem(RESULT), null);
    });

    test('a pending sign-in older than 10 minutes is ignored', async () => {
        const { win, server, login } = setup();
        win.sessionStorage.setItem(
            PENDING,
            JSON.stringify({
                state: STATE,
                code_verifier: 'v'.repeat(43),
                return_path: '/',
                org: 3,
                created_at: Date.now() - 600_001,
            })
        );
        win.sessionStorage.setItem(RESULT, JSON.stringify({ state: STATE, code: CODE }));
        void login.start();

        await nextSilentFrame(win);

        assert.equal(server.tokenRequests.length, 0);
    });

    test('a returned access_denied is the access-denied state; an unexpected answer fails without a loop', async () => {
        for (const [result, expected] of [
            [{ state: STATE, error: 'access_denied' }, 'access-denied'],
            [{ state: STATE, error: 'login_required' }, 'failed'],
            [{ state: STATE, code: 'short' }, 'failed'],
        ] as const) {
            const { win, login } = setup();
            win.sessionStorage.setItem(
                PENDING,
                JSON.stringify({
                    state: STATE,
                    code_verifier: 'v'.repeat(43),
                    return_path: '/',
                    org: 3,
                    created_at: Date.now(),
                })
            );
            win.sessionStorage.setItem(RESULT, JSON.stringify(result));

            assert.equal(await login.start(), expected, JSON.stringify(result));
            assert.deepEqual(win.location.replacements, []);
            assert.equal(win.document.frames.length, 0);
        }
    });
});

describe('the token exchange', () => {
    test('403 plugin_access_denied is the access-denied state; any other refusal fails', async () => {
        const denied = setup();
        denied.server.tokenResponder = () => json(403, { status_code: 403, code: 'plugin_access_denied', message: '' });
        const deniedStart = denied.login.start();
        await answerSilently(denied.win, { code: CODE });
        assert.equal(await deniedStart, 'access-denied');

        const refused = setup();
        refused.server.tokenResponder = () => json(400, { status_code: 400, code: 'invalid_grant', message: '' });
        const refusedStart = refused.login.start();
        await answerSilently(refused.win, { code: CODE });
        assert.equal(await refusedStart, 'failed');
        assert.equal(refused.login.error?.code, 'exchange_failed');
        assert.match(refused.login.error?.message ?? '', /invalid_grant/);
    });

    test('a token for another plugin, or a body of the wrong shape, fails', async () => {
        for (const body of [
            tokenBody('t', { plugin: { identifier: 'atlas', version: '1.0.0' } }),
            tokenBody('t', { token_type: 'MAC' }),
            tokenBody('t', { expires_in: '900' }),
            tokenBody(''),
        ]) {
            const { win, server, login } = setup();
            server.tokenResponder = () => json(200, body);
            const started = login.start();
            await answerSilently(win, { code: CODE });
            assert.equal(await started, 'failed');
            assert.equal(login.error?.code, 'invalid_token_response');
        }
    });
});

describe('fetch', () => {
    test('adds the token only to requests to the page origin under api_base', async () => {
        const { server, login } = await signedIn();

        for (const url of ['/api/whoami', 'api/whoami?x=1', `${PLUGIN_ORIGIN}/api/popup-relay/1.x`, '/api']) {
            await login.fetch(url);
        }
        for (const url of [
            '/apix/whoami',
            '/.well-known/epicstaff/config.json',
            '/api/../.well-known/epicstaff/config.json',
            '/',
            `${EPICSTAFF_ORIGIN}/api/graphs/`,
            'https://evil.example/api/whoami',
            'http://weather.plugins.epicstaff.example.com/api/whoami',
        ]) {
            await login.fetch(url);
        }

        assert.deepEqual(
            server.apiRequests.map((request) => [new URL(request.url).pathname, request.authorization]),
            [
                ['/api/whoami', 'Bearer token-1'],
                ['/api/whoami', 'Bearer token-1'],
                ['/api/popup-relay/1.x', 'Bearer token-1'],
                ['/api', 'Bearer token-1'],
                ['/apix/whoami', null],
                ['/.well-known/epicstaff/config.json', null],
                ['/.well-known/epicstaff/config.json', null],
                ['/', null],
                ['/api/graphs/', null],
                ['/api/whoami', null],
                ['/api/whoami', null],
            ]
        );
    });

    test('keeps the caller’s headers and resolves relative URLs against the page origin', async () => {
        const { server, login } = await signedIn();

        await login.fetch('/api/popup-relay', {
            method: 'POST',
            headers: { 'content-type': 'application/json' },
            body: '{}',
        });

        const [request] = server.apiRequests;
        assert.equal(request?.url, `${PLUGIN_ORIGIN}/api/popup-relay`);
        assert.equal(request?.init.method, 'POST');
        assert.equal(new Headers(request?.init.headers).get('content-type'), 'application/json');
    });

    test('renews silently once and retries once when the gateway refuses the token', async () => {
        const { win, server, login } = await signedIn();
        server.apiResponder = (request) =>
            request.authorization === 'Bearer token-1' ? gatewayDeny(401, 'login') : json(200, { mode: 'user' });

        const response = login.fetch('/api/whoami');
        const renewal = await answerSilently(win, { code: OTHER_CODE });

        assert.equal((await response).status, 200);
        assert.equal(renewal.url.searchParams.get('org'), '3', 'a renewal names the token’s org');
        assert.deepEqual(
            server.apiRequests.map((request) => request.authorization),
            ['Bearer token-1', 'Bearer token-2']
        );
        assert.deepEqual(win.location.replacements, []);
    });

    test('retries only once', async () => {
        const { win, server, login } = await signedIn();
        server.apiResponder = () => gatewayDeny(401, 'login');

        const response = login.fetch('/api/whoami');
        await answerSilently(win, { code: OTHER_CODE });

        assert.equal((await response).status, 401);
        assert.equal(server.apiRequests.length, 2);
        assert.equal(win.document.frames.length, 2, 'one renewal only');
    });

    test('moves to access-denied without a retry when the gateway refuses the person', async () => {
        const { server, login } = await signedIn();
        server.apiResponder = () => gatewayDeny(403, 'forbidden');

        const response = await login.fetch('/api/whoami');

        assert.equal(response.status, 403);
        assert.equal(await response.text(), JSON.stringify({ status_code: 403, code: 'forbidden', message: '' }));
        assert.equal(login.state, 'access-denied');
        assert.equal(server.apiRequests.length, 1);
        await login.fetch('/api/whoami');
        assert.equal(server.apiRequests[1]?.authorization, null, 'the token is gone');
    });

    test('returns the plugin’s own 401 and 403 as they are, whatever their body says', async () => {
        const { win, server, login } = await signedIn();
        const changes: string[] = [];
        login.onChange((state) => changes.push(state));

        for (const own of [
            json(401, { code: 'login_required' }),
            json(403, { status_code: 403, code: 'forbidden', message: 'Only admins may change the units.' }),
        ]) {
            server.apiResponder = () => own;
            const response = await login.fetch('/api/settings');
            assert.equal(response.status, own.status);
        }
        await flush();

        assert.equal(login.state, 'signed-in');
        assert.deepEqual(changes, []);
        assert.equal(win.document.frames.length, 1, 'no renewal');
        assert.deepEqual(
            server.apiRequests.map((request) => request.authorization),
            ['Bearer token-1', 'Bearer token-1'],
            'no retry, and the token is kept'
        );
    });

    test('acts only on the pairs the gateway sends: 401 with login, 403 with forbidden', async () => {
        const { win, server, login } = await signedIn();

        for (const response of [
            gatewayDeny(401, 'forbidden'),
            gatewayDeny(403, 'login'),
            gatewayDeny(401, 'LOGIN'),
            json(429, {}, { 'X-EpicStaff-Gateway-Deny': 'rate_limited' }),
            json(503, {}, { 'X-EpicStaff-Gateway-Deny': 'unavailable' }),
        ]) {
            server.apiResponder = () => response;
            assert.equal((await login.fetch('/api/whoami')).status, response.status);
        }
        await flush();

        assert.equal(login.state, 'signed-in');
        assert.equal(win.document.frames.length, 1, 'no renewal');
        assert.equal(server.apiRequests.length, 5, 'no retry');
    });
});

describe('fetch alongside renewals', () => {
    test('two requests refused at once share exactly one renewal, then both retry with the new token', async () => {
        const { win, server, login } = await signedIn();
        server.apiResponder = (request) =>
            request.authorization === 'Bearer token-1' ? gatewayDeny(401, 'login') : json(200, {});

        const first = login.fetch('/api/whoami');
        const second = login.fetch('/api/settings');
        await until(() => server.apiRequests.length === 2);
        await answerSilently(win, { code: OTHER_CODE });

        assert.deepEqual([(await first).status, (await second).status], [200, 200]);
        assert.equal(win.document.frames.length, 2, 'the sign-in, and one renewal');
        assert.deepEqual(
            server.apiRequests.map((request) => request.authorization),
            ['Bearer token-1', 'Bearer token-1', 'Bearer token-2', 'Bearer token-2']
        );
    });

    test('a refusal that arrives after a renewal retries with the new token without renewing again', async () => {
        const { win, server, login } = await signedIn();
        let releaseFirst: (response: Response) => void = () => undefined;
        server.apiResponder = (request) =>
            request.authorization === 'Bearer token-1'
                ? new Promise<Response>((resolve) => (releaseFirst = resolve))
                : json(200, {});

        const late = login.fetch('/api/whoami');
        await until(() => server.apiRequests.length === 1);
        const renewed = login.renew();
        await answerSilently(win, { code: OTHER_CODE });
        assert.equal(await renewed, 'signed-in');
        releaseFirst(gatewayDeny(401, 'login'));

        assert.equal((await late).status, 200);
        assert.deepEqual(
            server.apiRequests.map((request) => request.authorization),
            ['Bearer token-1', 'Bearer token-2']
        );
        assert.equal(win.document.frames.length, 2, 'no second renewal');
    });

    test('never retries a request whose body is a stream', async () => {
        const { win, server, login } = await signedIn();
        server.apiResponder = () => gatewayDeny(401, 'login');

        const response = login.fetch('/api/upload', {
            method: 'POST',
            body: new ReadableStream({ start: (controller) => controller.close() }),
            duplex: 'half',
        } as RequestInit);
        await answerSilently(win, { code: OTHER_CODE });

        assert.equal((await response).status, 401);
        assert.equal(server.apiRequests.length, 1);
        assert.equal(login.state, 'signed-in', 'the renewal still happened, for the next request');
    });

    test('waits for a renewal already under way, then sends the new token', async () => {
        const { win, server, login } = await signedIn();

        const renewing = login.renew();
        const silent = await nextSilentFrame(win);
        const response = login.fetch('/api/whoami');
        await flush();
        assert.equal(server.apiRequests.length, 0, 'nothing sent during the renewal');
        postFromFrame(win, silent, { code: OTHER_CODE });

        assert.equal(await renewing, 'signed-in');
        assert.equal((await response).status, 200);
        assert.deepEqual(
            server.apiRequests.map((request) => request.authorization),
            ['Bearer token-2']
        );
    });
});

describe('a token that fell due while timers were held back', () => {
    const START = 1_800_000_000_000;

    test('fetch renews first once the token is within 60 seconds of expiry', async () => {
        mock.timers.enable({ apis: ['Date'], now: START });
        const { win, server, login } = await signedIn();

        mock.timers.setTime(START + 839_000);
        await login.fetch('/api/whoami');
        assert.equal(win.document.frames.length, 1, 'not due yet');

        mock.timers.setTime(START + 840_000);
        const response = login.fetch('/api/whoami');
        await answerSilently(win, { code: OTHER_CODE });
        await response;

        assert.deepEqual(
            server.apiRequests.map((request) => request.authorization),
            ['Bearer token-1', 'Bearer token-2']
        );
    });

    test('a tab shown again renews a token that fell due meanwhile; a hidden one does not', async () => {
        mock.timers.enable({ apis: ['Date'], now: START });
        const { win, login } = await signedIn();
        mock.timers.setTime(START + 850_000);

        win.document.setVisibility('hidden');
        await flush();
        assert.equal(win.document.frames.length, 1);

        win.document.setVisibility('visible');
        await answerSilently(win, { code: OTHER_CODE });
        await until(() => login.session?.expiresAt === START + 850_000 + 900_000);

        win.document.setVisibility('visible');
        await flush();
        assert.equal(win.document.frames.length, 2, 'a fresh token is not renewed again');
    });
});

describe('a stored org hint EpicStaff refuses', () => {
    function pendingFor(org: number | null): string {
        return JSON.stringify({
            state: STATE,
            code_verifier: 'v'.repeat(43),
            return_path: '/me',
            org,
            created_at: Date.now(),
        });
    }

    function storedOrgSetup(windowOptions: FakeWindowOptions, orgHint: number | null): Setup {
        const win = new FakeWindow({ url: `${PLUGIN_ORIGIN}/me?x=1`, ...windowOptions });
        win.sessionStorage.setItem('epicstaff.login.org', '7');
        const server = new FakeServer();
        const login = createPluginLogin(pluginSource(orgHint), { window: win.asWindow(), fetch: server.fetch });
        cleanups.push(() => login.close());
        return { win, server, login };
    }

    test('on its own address, forgets the stored org and signs in without one', async () => {
        const { win, login } = storedOrgSetup({ framed: false }, null);
        const started = login.start();

        const silent = await answerSilently(win, { error: 'access_denied' });

        assert.equal(silent.url.searchParams.get('org'), '7');
        assert.equal(await started, 'signing-in');
        assert.equal(win.sessionStorage.getItem('epicstaff.login.org'), null);
        const authorize = new URL(win.location.replacements[0] ?? '');
        assert.equal(authorize.searchParams.has('org'), false);
        assert.equal(authorize.searchParams.has('prompt'), false);
        assert.equal(storedPending(win)['return_path'], '/me?x=1');
    });

    test('also when the refusal comes back from an interactive sign-in to the stored org', async () => {
        const { win, login } = storedOrgSetup({ framed: false }, null);
        win.sessionStorage.setItem(PENDING, pendingFor(7));
        win.sessionStorage.setItem(RESULT, JSON.stringify({ state: STATE, error: 'access_denied' }));

        assert.equal(await login.start(), 'signing-in');

        assert.equal(win.sessionStorage.getItem('epicstaff.login.org'), null);
        assert.equal(new URL(win.location.replacements[0] ?? '').searchParams.has('org'), false);
    });

    test('a refusal of the sign-in without an org is the answer: no loop', async () => {
        const win = new FakeWindow({ framed: false, url: `${PLUGIN_ORIGIN}/me` });
        win.sessionStorage.setItem(PENDING, pendingFor(null));
        win.sessionStorage.setItem(RESULT, JSON.stringify({ state: STATE, error: 'access_denied' }));
        const login = createPluginLogin(pluginSource(null), { window: win.asWindow(), fetch: new FakeServer().fetch });
        cleanups.push(() => login.close());

        assert.equal(await login.start(), 'access-denied');
        assert.deepEqual(win.location.replacements, []);
    });

    test('inside EpicStaff a refusal stays access-denied, with es_org or a stored org', async () => {
        for (const orgHint of [3, null]) {
            const { win, login } = storedOrgSetup({ framed: true }, orgHint);
            const started = login.start();
            await answerSilently(win, { error: 'access_denied' });

            assert.equal(await started, 'access-denied', String(orgHint));
            assert.deepEqual(win.location.replacements, []);
            assert.equal(win.sessionStorage.getItem('epicstaff.login.org'), '7');
        }
    });

    test('es_org on the plugin’s own address is EpicStaff’s answer too', async () => {
        const { win, login } = storedOrgSetup({ framed: false }, 3);
        const started = login.start();
        await answerSilently(win, { error: 'access_denied' });

        assert.equal(await started, 'access-denied');
        assert.deepEqual(win.location.replacements, []);
    });
});

describe('renewal', () => {
    test('renews silently 60 seconds before expiry, for the same org, and notifies', async () => {
        mock.timers.enable({ apis: ['setTimeout'] });
        const { win, server, login } = await signedIn();
        const changes: string[] = [];
        login.onChange((state) => changes.push(state));

        mock.timers.tick(839_999);
        await flush();
        assert.equal(win.document.frames.length, 1);
        mock.timers.tick(1);
        const renewal = await answerSilently(win, { code: OTHER_CODE });
        await until(() => changes.length === 1);

        assert.equal(renewal.url.searchParams.get('org'), '3');
        assert.equal(renewal.url.searchParams.get('prompt'), 'none');
        assert.deepEqual(changes, ['signed-in']);
        await login.fetch('/api/whoami');
        assert.equal(server.apiRequests[0]?.authorization, 'Bearer token-2');
    });

    test('renew() on demand gets a new token without navigating', async () => {
        const { win, login } = await signedIn();

        const renewed = login.renew();
        await answerSilently(win, { code: OTHER_CODE });

        assert.equal(await renewed, 'signed-in');
        assert.deepEqual(win.location.replacements, []);
    });

    test('login_required inside EpicStaff ends the session without navigating; signIn() then navigates', async () => {
        const { win, login } = await signedIn();

        const renewed = login.renew();
        await answerSilently(win, { error: 'login_required' });

        assert.equal(await renewed, 'session-ended');
        assert.equal(login.session, null);
        await flush();
        assert.deepEqual(win.location.replacements, []);

        await login.signIn();
        assert.equal(win.location.replacements.length, 1);
        assert.equal(new URL(win.location.replacements[0] ?? '').searchParams.get('org'), '3');
    });

    test('login_required on a page opened on its own goes to EpicStaff’s login at once', async () => {
        const { win, login } = await signedIn({ framed: false });

        const renewed = login.renew();
        await answerSilently(win, { error: 'login_required' });

        assert.equal(await renewed, 'session-ended');
        await until(() => win.location.replacements.length === 1);
        assert.equal(new URL(win.location.replacements[0] ?? '').searchParams.has('prompt'), false);
    });

    test('access_denied on renewal is the access-denied state', async () => {
        const { win, login } = await signedIn();

        const renewed = login.renew();
        await answerSilently(win, { error: 'access_denied' });

        assert.equal(await renewed, 'access-denied');
    });
});

describe('organization hint', () => {
    test('on its own, the page signs in to the org of this tab’s last token', async () => {
        const win = new FakeWindow({ framed: false });
        win.sessionStorage.setItem('epicstaff.login.org', '7');
        const login = createPluginLogin(pluginSource(null), { window: win.asWindow(), fetch: new FakeServer().fetch });
        cleanups.push(() => login.close());
        void login.start();

        const { url } = await nextSilentFrame(win);

        assert.equal(url.searchParams.get('org'), '7');
    });

    test('es_org wins over the stored org', async () => {
        const win = new FakeWindow();
        win.sessionStorage.setItem('epicstaff.login.org', '7');
        const login = createPluginLogin(pluginSource(3), { window: win.asWindow(), fetch: new FakeServer().fetch });
        cleanups.push(() => login.close());
        void login.start();

        const { url } = await nextSilentFrame(win);

        assert.equal(url.searchParams.get('org'), '3');
    });
});

describe('close', () => {
    test('removes the hidden frame and stops waiting', async () => {
        const { win, login } = setup();
        void login.start();
        const silent = await nextSilentFrame(win);

        login.close();

        assert.equal(silent.frame.removed, true);
        assert.equal(win.messageListenerCount, 0);
    });
});
