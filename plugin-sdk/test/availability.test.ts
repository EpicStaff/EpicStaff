import assert from 'node:assert/strict';
import { afterEach, describe, mock, test } from 'node:test';

import {
    createPluginLogin,
    type EpicStaffPlugin,
    gatewayRefusal,
    type PluginAvailability,
    type PluginLogin,
    type PluginLoginSource,
    startPlugin,
} from '../dist/index.js';
import { AvailabilityReporter } from '../dist/frame.js';
import {
    answerSilently,
    AUTHORIZE_URL,
    CODE,
    FakeServer,
    gatewayDeny,
    json,
    pluginSource,
    TOKEN_URL,
} from './helpers/fake-login.ts';
import {
    closeFakeHosts,
    configFetch,
    FakeWindow,
    type FakeWindowOptions,
    frameWithHost,
    PLUGIN_ORIGIN,
    waitFor,
} from './helpers/fake-window.ts';

const PENDING = 'epicstaff.login.pending';
const RESULT = 'epicstaff.login.result';
const STATE = 'S'.repeat(43);

const cleanups: (() => void)[] = [];
afterEach(() => {
    while (cleanups.length > 0) cleanups.pop()?.();
    mock.timers.reset();
    closeFakeHosts();
});

/** A gateway 503 as nginx answers it: the reason in the header, `Retry-After`, EpicStaff's JSON body. */
function gateway503(reason: 'maintenance' | 'unavailable'): Response {
    const code = reason === 'maintenance' ? 'plugin_maintenance' : 'plugin_unavailable';
    return json(
        503,
        { status_code: 503, code, message: '' },
        { 'X-EpicStaff-Gateway-Deny': reason, 'Retry-After': '30' }
    );
}

interface Setup {
    win: FakeWindow;
    server: FakeServer;
    login: PluginLogin;
    /** What the login told `reportAvailability`, in order. */
    reports: PluginAvailability[];
    /** What `onAvailabilityChange` heard, in order. */
    changes: PluginAvailability[];
}

function setup(windowOptions: FakeWindowOptions = {}): Setup {
    const win = new FakeWindow({ url: `${PLUGIN_ORIGIN}/places`, ...windowOptions });
    const server = new FakeServer();
    const reports: PluginAvailability[] = [];
    const source: PluginLoginSource = { ...pluginSource(3), reportAvailability: (state) => reports.push(state) };
    const login = createPluginLogin(source, { window: win.asWindow(), fetch: server.fetch });
    const changes: PluginAvailability[] = [];
    login.onAvailabilityChange((state) => changes.push(state));
    cleanups.push(() => login.close());
    return { win, server, login, reports, changes };
}

async function signedIn(windowOptions: FakeWindowOptions = {}): Promise<Setup> {
    const context = setup(windowOptions);
    const started = context.login.start();
    await answerSilently(context.win, { code: CODE });
    assert.equal(await started, 'signed-in');
    return context;
}

function storeReturnedSignIn(win: FakeWindow, result: Record<string, unknown>): void {
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
    win.sessionStorage.setItem(RESULT, JSON.stringify({ state: STATE, ...result }));
}

describe('gatewayRefusal', () => {
    test('reads the reason and Retry-After of a refusal the gateway answered itself', () => {
        assert.deepEqual(gatewayRefusal(gateway503('maintenance')), { reason: 'maintenance', retryAfterSeconds: 30 });
        assert.deepEqual(gatewayRefusal(gatewayDeny(401, 'login')), { reason: 'login', retryAfterSeconds: null });
    });

    test('is null for the plugin’s own answers and for a reason this SDK does not know', () => {
        assert.equal(gatewayRefusal(json(503, { code: 'busy' })), null);
        assert.equal(gatewayRefusal(json(503, {}, { 'X-EpicStaff-Gateway-Deny': 'MAINTENANCE' })), null);
        assert.equal(gatewayRefusal(json(503, {}, { 'X-EpicStaff-Gateway-Deny': 'later' })), null);
    });

    test('takes only a whole number of seconds from Retry-After', () => {
        for (const [value, expected] of [
            ['0', 0],
            [' 45 ', 45],
            ['1.5', null],
            ['-1', null],
            ['Wed, 21 Oct 2026 07:28:00 GMT', null],
        ] as const) {
            const response = json(503, {}, { 'X-EpicStaff-Gateway-Deny': 'maintenance', 'Retry-After': value });
            assert.equal(gatewayRefusal(response)?.retryAfterSeconds, expected, value);
        }
    });
});

describe('availability of the plugin’s API', () => {
    test('is available until an answer says otherwise', async () => {
        const { login } = await signedIn();
        assert.equal(login.availability, 'available');
    });

    test('a gateway 503 maintenance or unavailable sets it, and is returned as it is without a renewal', async () => {
        const { win, server, login, reports, changes } = await signedIn();

        server.apiResponder = () => gateway503('maintenance');
        const refused = await login.fetch('/api/places');
        assert.equal(refused.status, 503);
        assert.equal(((await refused.json()) as { code: string }).code, 'plugin_maintenance');
        assert.equal(login.availability, 'maintenance');

        server.apiResponder = () => gateway503('unavailable');
        await login.fetch('/api/places');
        assert.equal(login.availability, 'unavailable');

        assert.equal(login.state, 'signed-in');
        assert.equal(win.document.frames.length, 1, 'no renewal');
        assert.equal(server.apiRequests.length, 2, 'no retry');
        assert.deepEqual(changes, ['maintenance', 'unavailable']);
        assert.deepEqual(reports, ['maintenance', 'unavailable']);
    });

    test('any answer that passed the gateway makes it available again, the plugin’s own 503 too', async () => {
        const { server, login, changes } = await signedIn();
        server.apiResponder = () => gateway503('maintenance');
        await login.fetch('/api/places');

        server.apiResponder = () => json(503, { code: 'busy' });
        await login.fetch('/api/places');

        assert.equal(login.availability, 'available');
        assert.deepEqual(changes, ['maintenance', 'available']);
    });

    test('the gateway’s other refusals leave it as it is', async () => {
        const { server, login, changes } = await signedIn();
        server.apiResponder = () => gateway503('maintenance');
        await login.fetch('/api/places');

        for (const response of [
            gatewayDeny(403, 'forbidden'),
            json(429, {}, { 'X-EpicStaff-Gateway-Deny': 'rate_limited' }),
            json(503, {}, { 'X-EpicStaff-Gateway-Deny': 'not_found' }),
        ]) {
            server.apiResponder = () => response;
            await login.fetch('/api/places');
        }

        assert.equal(login.availability, 'maintenance');
        assert.deepEqual(changes, ['maintenance']);
    });

    test('a request without a token counts too: maintenance covers public paths', async () => {
        const { server, login } = setup();
        server.apiResponder = () => gateway503('maintenance');

        const response = await login.fetch('/api/ping');

        assert.equal(response.status, 503);
        assert.equal(server.apiRequests[0]?.authorization, null);
        assert.equal(login.availability, 'maintenance');
    });

    test('requests to another origin say nothing about the plugin’s API', async () => {
        const { server, login } = setup();
        server.apiResponder = () => gateway503('maintenance');

        await login.fetch('https://api.open-meteo.com/v1/forecast');

        assert.equal(login.availability, 'available');
    });

    test('nothing is reported once the login is closed', async () => {
        const { server, login, reports, changes } = await signedIn();
        const pending = (async () => {
            server.apiResponder = () => gateway503('maintenance');
            return login.fetch('/api/places');
        })();
        login.close();
        await pending;

        assert.deepEqual(reports, []);
        assert.deepEqual(changes, []);
    });
});

describe('signing in while the plugin is being updated in the organization', () => {
    test('temporarily_unavailable at start is the maintenance state, without navigating', async () => {
        const { win, server, login, changes } = setup({ framed: false });
        const started = login.start();

        await answerSilently(win, { error: 'temporarily_unavailable' });

        assert.equal(await started, 'maintenance');
        assert.equal(login.availability, 'maintenance');
        assert.equal(login.session, null);
        assert.deepEqual(win.location.replacements, [], 'no trip to EpicStaff’s login, so no loop');
        assert.equal(server.tokenRequests.length, 0);
        assert.deepEqual(changes, ['maintenance']);
    });

    test('renew() tries again and signs in once the organization is back', async () => {
        const { win, login } = setup();
        const started = login.start();
        await answerSilently(win, { error: 'temporarily_unavailable' });
        await started;

        const renewed = login.renew();
        await answerSilently(win, { code: CODE });

        assert.equal(await renewed, 'signed-in');
        assert.equal(login.session?.org.id, 3);
        assert.equal(new URL(win.document.frames[1]?.src ?? '').searchParams.get('org'), '3', 'the same org');
        assert.equal(login.availability, 'available', 'a sign-in that works again ends the maintenance');
    });

    test('a renewal refused for good after the update ends the maintenance: the page shows why', async () => {
        const { win, login, changes } = setup();
        const started = login.start();
        await answerSilently(win, { error: 'temporarily_unavailable' });
        assert.equal(await started, 'maintenance');

        // The organization's upgrade failed for good: EpicStaff no longer signs the person in to the plugin.
        const renewed = login.renew();
        await answerSilently(win, { error: 'access_denied' });

        assert.equal(await renewed, 'access-denied');
        assert.equal(login.state, 'access-denied');
        assert.equal(login.availability, 'available');
        assert.deepEqual(changes, ['maintenance', 'available']);
    });

    test('an ended session or a failed sign-in after the update ends the maintenance too', async () => {
        for (const outcome of ['session-ended', 'failed'] as const) {
            const { win, server, login } = setup();
            const started = login.start();
            await answerSilently(win, { error: 'temporarily_unavailable' });
            await started;

            if (outcome === 'failed') {
                server.tokenResponder = () => json(400, { status_code: 400, code: 'invalid_grant', message: '' });
            }
            const renewed = login.renew();
            await answerSilently(win, outcome === 'failed' ? { code: CODE } : { error: 'login_required' });

            assert.equal(await renewed, outcome);
            assert.equal(login.availability, 'available', outcome);
            login.close();
        }
    });

    test('a refused sign-in leaves a maintenance the API answered as it is', async () => {
        const { win, server, login } = await signedIn();
        server.apiResponder = () => gateway503('maintenance');
        await login.fetch('/api/places');

        const renewed = login.renew();
        await answerSilently(win, { error: 'access_denied' });

        assert.equal(await renewed, 'access-denied');
        assert.equal(login.availability, 'maintenance');
    });

    test('a maintenance the API answered stays through a sign-in refused for it, then a failed one', async () => {
        const { win, server, login, changes, reports } = await signedIn();
        server.apiResponder = () => gateway503('maintenance');
        await login.fetch('/api/places');

        const held = login.renew();
        await answerSilently(win, { error: 'temporarily_unavailable' });
        assert.equal(await held, 'maintenance');
        assert.equal(login.availability, 'maintenance');

        server.tokenResponder = () => json(400, { status_code: 400, code: 'invalid_grant', message: '' });
        const failed = login.renew();
        await answerSilently(win, { code: CODE });

        assert.equal(await failed, 'failed');
        assert.equal(login.availability, 'maintenance', 'only the API, or a sign-in that gets a token, ends it');
        assert.deepEqual(changes, ['maintenance']);
        assert.deepEqual(reports, ['maintenance']);

        server.apiResponder = () => json(200, {});
        await login.fetch('/api/places');
        assert.equal(login.availability, 'available', 'the API says it is back');
    });

    test('a refused sign-in leaves an unavailable API as it is', async () => {
        const { win, server, login } = await signedIn();
        server.apiResponder = () => gateway503('unavailable');
        await login.fetch('/api/places');

        const renewed = login.renew();
        await answerSilently(win, { error: 'access_denied' });

        assert.equal(await renewed, 'access-denied');
        assert.equal(login.availability, 'unavailable');
    });

    test('a sign-in leaves an unavailable API as it is: only the API itself says it is back', async () => {
        const { win, server, login } = await signedIn();
        server.apiResponder = () => gateway503('unavailable');
        await login.fetch('/api/places');

        const renewed = login.renew();
        await answerSilently(win, { code: CODE });
        await renewed;

        assert.equal(login.availability, 'unavailable');
    });

    test('temporarily_unavailable on renewal drops the token', async () => {
        const { win, server, login } = await signedIn();

        const renewed = login.renew();
        await answerSilently(win, { error: 'temporarily_unavailable' });

        assert.equal(await renewed, 'maintenance');
        assert.equal(login.availability, 'maintenance');
        server.apiResponder = () => gatewayDeny(401, 'login');
        await login.fetch('/api/whoami');
        assert.equal(server.apiRequests.at(-1)?.authorization, null, 'no token is sent any more');
    });

    test('an interactive sign-in that came back with temporarily_unavailable is the maintenance state', async () => {
        const { win, login } = setup();
        storeReturnedSignIn(win, { error: 'temporarily_unavailable' });

        assert.equal(await login.start(), 'maintenance');
        assert.equal(login.error, null);
        assert.deepEqual(win.location.replacements, []);
        assert.equal(win.document.frames.length, 0);
    });
});

describe('AvailabilityReporter', () => {
    function reporter(): { sent: PluginAvailability[]; reporter: AvailabilityReporter } {
        const sent: PluginAvailability[] = [];
        const created = new AvailabilityReporter((state) => sent.push(state));
        cleanups.push(() => created.close());
        return { sent, reporter: created };
    }

    test('sends maintenance and unavailable at once, never available', () => {
        mock.timers.enable({ apis: ['setTimeout'] });
        const { sent, reporter: subject } = reporter();

        subject.report('available');
        subject.report('maintenance');

        assert.deepEqual(sent, ['maintenance']);
    });

    test('sends at most once per 30 seconds, and the latest state when the window ends', () => {
        mock.timers.enable({ apis: ['setTimeout'] });
        const { sent, reporter: subject } = reporter();

        subject.report('unavailable');
        mock.timers.tick(10_000);
        subject.report('maintenance');
        mock.timers.tick(19_999);
        assert.deepEqual(sent, ['unavailable'], 'nothing more inside the window');

        mock.timers.tick(1);
        assert.deepEqual(sent, ['unavailable', 'maintenance'], 'the change made inside the window is not lost');

        subject.report('unavailable');
        mock.timers.tick(30_000);
        assert.deepEqual(sent, ['unavailable', 'maintenance', 'unavailable']);
    });

    test('a window that ends with the API available again sends nothing', () => {
        mock.timers.enable({ apis: ['setTimeout'] });
        const { sent, reporter: subject } = reporter();

        subject.report('maintenance');
        subject.report('unavailable');
        subject.report('available');
        mock.timers.tick(30_000);
        subject.report('maintenance');

        assert.deepEqual(sent, ['maintenance', 'maintenance'], 'a new window starts after the quiet end');
    });

    test('sends nothing once closed', () => {
        mock.timers.enable({ apis: ['setTimeout'] });
        const { sent, reporter: subject } = reporter();

        subject.report('maintenance');
        subject.report('unavailable');
        subject.close();
        mock.timers.tick(30_000);
        subject.report('maintenance');

        assert.deepEqual(sent, ['maintenance']);
    });
});

describe('availability.changed on the frame port', () => {
    async function start(win: FakeWindow): Promise<EpicStaffPlugin> {
        const login = { authorize_url: AUTHORIZE_URL, token_url: TOKEN_URL };
        const plugin = await startPlugin({ window: win.asWindow(), fetch: configFetch({ login }) });
        cleanups.push(() => plugin.close());
        return plugin;
    }

    test('a framed page’s login posts it when its API answers maintenance', async () => {
        const win = new FakeWindow();
        const host = frameWithHost(win);
        const plugin = await start(win);
        const server = new FakeServer();
        server.apiResponder = () => gateway503('maintenance');
        const login = createPluginLogin(plugin, { window: win.asWindow(), fetch: server.fetch });
        cleanups.push(() => login.close());

        await login.fetch('/api/ping');
        await login.fetch('/api/ping');

        await waitFor(() => host.received.length === 1);
        assert.deepEqual(host.received, [{ type: 'availability.changed', state: 'maintenance' }]);
    });

    test('available is never posted; maintenance and unavailable are', async () => {
        const win = new FakeWindow();
        const host = frameWithHost(win);
        const plugin = await start(win);

        plugin.reportAvailability('available');
        plugin.reportAvailability('unavailable');

        await waitFor(() => host.received.length === 1);
        assert.deepEqual(host.received, [{ type: 'availability.changed', state: 'unavailable' }]);
    });

    test('unframed, reporting does nothing', async () => {
        const win = new FakeWindow({ framed: false });
        const plugin = await start(win);

        assert.doesNotThrow(() => plugin.reportAvailability('maintenance'));
        assert.equal(plugin.framed, false);
    });
});
