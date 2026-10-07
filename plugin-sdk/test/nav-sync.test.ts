import assert from 'node:assert/strict';
import { afterEach, describe, test } from 'node:test';

import { canonicalNavPath, connect, type EpicStaffBridge, hashToNavPath } from '../dist/index.js';
import { createMockHost, type MockHost } from '../dist/mock-host.js';
import { delay, FakeWindow, frameWithHost, waitFor } from './helpers/fake-window.ts';

const cleanups: Array<() => void> = [];
afterEach(() => {
    while (cleanups.length > 0) cleanups.pop()?.();
});

function mockHost(initialPath?: string): MockHost {
    const host = createMockHost({ latencyMs: 0, ...(initialPath === undefined ? {} : { initialPath }) });
    cleanups.push(() => host.close());
    return host;
}

async function connectFramed(win: FakeWindow, host: MockHost, initDelayMs?: number): Promise<EpicStaffBridge> {
    frameWithHost(win, host, initDelayMs === undefined ? {} : { initDelayMs });
    const bridge = await connect({ window: win.asWindow() });
    cleanups.push(() => bridge.close());
    return bridge;
}

describe('nav sync inside EpicStaff', () => {
    test('turns pushState into replaceState and reports {replace: false}', async () => {
        const win = new FakeWindow();
        const host = mockHost();
        await connectFramed(win, host);

        win.history.pushState({ navigationId: 2 }, '', '#/conversations?page=2');

        assert.equal(win.location.hash, '#/conversations?page=2');
        assert.equal(win.history.length, 1, 'no entry is added to the frame history');
        assert.deepEqual(
            win.history.calls.map((call) => call.method),
            ['replaceState']
        );
        await waitFor(() => host.navChanges.length === 1);
        assert.deepEqual(host.navChanges, [{ path: '/conversations?page=2', replace: false }]);
    });

    test('reports replaceState with {replace: true}, and never the path EpicStaff already shows', async () => {
        const win = new FakeWindow();
        const host = mockHost();
        await connectFramed(win, host);

        win.history.replaceState(null, '', '#/chat');
        win.history.replaceState({ navigationId: 3 }, '', '#/chat');
        win.history.pushState(null, '', '#/chat');

        await delay(20);
        assert.deepEqual(host.navChanges, [{ path: '/chat', replace: true }]);
    });

    test('queues changes made before the handshake; the latest wins', async () => {
        const win = new FakeWindow();
        const host = mockHost('/');
        const connecting = connectFramed(win, host, 20);

        // The router's first navigation and a redirect, before EpicStaff answered.
        win.history.replaceState(null, '', '#/chat');
        win.history.replaceState(null, '', '#/chat/c_0123456789abcdef01234567');
        await connecting;

        await waitFor(() => host.navChanges.length === 1);
        await delay(20);
        assert.deepEqual(host.navChanges, [{ path: '/chat/c_0123456789abcdef01234567', replace: true }]);
    });

    test("moves the app to EpicStaff's path when the frame did not start on it", async () => {
        const win = new FakeWindow({ url: 'http://localhost:4300/#/chat' });
        const host = mockHost('/conversations/c_1');
        const bridge = await connectFramed(win, host);

        assert.equal(win.location.hash, '#/conversations/c_1');
        assert.deepEqual(win.dispatched, ['popstate', 'hashchange']);
        assert.equal(bridge.nav.path, '/conversations/c_1');
        await delay(20);
        assert.deepEqual(host.navChanges, []);
    });

    test('nav.navigate sets the hash, fires popstate + hashchange, and is not echoed back', async () => {
        const win = new FakeWindow();
        const host = mockHost();
        const bridge = await connectFramed(win, host);
        const navigated: string[] = [];
        bridge.nav.onNavigate((path) => navigated.push(path));
        let popstates = 0;
        win.addEventListener('popstate', () => {
            popstates++;
            // What a router does on popstate: navigate, then write the same URL back.
            win.history.replaceState({ navigationId: 9 }, '', '#/about');
        });

        host.navigate('/about');
        await waitFor(() => navigated.length === 1);

        assert.equal(win.location.hash, '#/about');
        assert.equal(popstates, 1);
        assert.ok(win.dispatched.includes('hashchange'));
        assert.deepEqual(navigated, ['/about']);
        await delay(20);
        assert.deepEqual(host.navChanges, [], 'the router writing the same URL is not reported');
    });

    test('compares paths in the canonical spelling, so a router re-spelling the URL is no echo', async () => {
        const win = new FakeWindow();
        const host = mockHost();
        await connectFramed(win, host);
        let popstates = 0;
        win.addEventListener('popstate', () => {
            popstates++;
            // A router that spells the same URL its own way: ":" unescaped, "+" for a space.
            win.history.replaceState(null, '', '#/notes/a:b?q=hello+world');
        });

        host.navigate('/notes/a%3Ab?q=hello%20world');
        await waitFor(() => popstates === 1);

        await delay(20);
        assert.deepEqual(host.navChanges, []);
        win.history.pushState(null, '', '#/notes/a:b?q=hello+world&page=2');
        await waitFor(() => host.navChanges.length === 1);
        assert.deepEqual(host.navChanges, [{ path: '/notes/a%3Ab?q=hello%20world&page=2', replace: false }]);
    });

    test('a custom onNavigate replaces the default handling', async () => {
        const win = new FakeWindow();
        const host = mockHost();
        frameWithHost(win, host);
        const routed: string[] = [];
        const bridge = await connect({ window: win.asWindow(), navSync: { onNavigate: (path) => routed.push(path) } });
        cleanups.push(() => bridge.close());

        host.navigate('/conversations');
        await waitFor(() => routed.length === 1);

        assert.deepEqual(routed, ['/conversations']);
        assert.equal(win.location.hash, '#/');
        assert.deepEqual(win.dispatched, []);
    });

    test('close() restores history.pushState and history.replaceState', async () => {
        const win = new FakeWindow();
        const bridge = await connectFramed(win, mockHost());
        assert.equal(Object.hasOwn(win.history, 'pushState'), true);

        bridge.close();

        assert.equal(Object.hasOwn(win.history, 'pushState'), false);
        assert.equal(Object.hasOwn(win.history, 'replaceState'), false);
    });
});

describe('nav sync outside EpicStaff (mock host)', () => {
    test('keeps pushState a real push and still reports it', async () => {
        const win = new FakeWindow({ framed: false, url: 'http://localhost:4300/#/chat' });
        const host = mockHost();
        const bridge = await connect({ window: win.asWindow(), mock: host });
        cleanups.push(() => bridge.close());

        win.history.pushState(null, '', '#/about');

        assert.equal(win.history.length, 2);
        await waitFor(() => host.navChanges.length === 1);
        assert.deepEqual(host.navChanges, [{ path: '/about', replace: false }]);
        assert.equal(bridge.context.nav.path, '/chat', 'the mock reports the page path at the handshake');
    });
});

describe('hashToNavPath', () => {
    test('canonicalises hash routes to the bridge path grammar', () => {
        assert.equal(hashToNavPath(''), '/');
        assert.equal(hashToNavPath('#'), '/');
        assert.equal(hashToNavPath('#/'), '/');
        assert.equal(hashToNavPath('#/conversations/'), '/conversations');
        assert.equal(hashToNavPath('#/a//b'), '/a/b');
        assert.equal(hashToNavPath('#/a b/c'), '/a%20b/c');
        assert.equal(hashToNavPath('#/x;y=1:2'), '/x%3By%3D1%3A2');
        assert.equal(
            hashToNavPath('#/conversations?search=a b&ordering=-updated_at&page=2'),
            '/conversations?search=a%20b&ordering=-updated_at&page=2'
        );
        assert.equal(hashToNavPath('#/c?x=a:b,c'), '/c?x=a%3Ab%2Cc');
        assert.equal(hashToNavPath('#/ok%20done'), '/ok%20done');
        assert.equal(hashToNavPath('#/100%'), '/100%25');
        assert.equal(hashToNavPath('#/café'), '/caf%C3%A9');
        assert.equal(hashToNavPath('#/a#section'), '/a');
        assert.equal(hashToNavPath('#/a?'), '/a');
        assert.equal(hashToNavPath('#/c?q=a+b'), '/c?q=a%20b', '"+" in a query is a space');
        assert.equal(hashToNavPath('#/%7euser'), '/~user', 'unreserved characters are not escaped');
        assert.equal(hashToNavPath('#/x%3ay'), '/x%3Ay', 'escapes use uppercase hex');
        assert.equal(hashToNavPath('#/c?flag'), '/c?flag=');
        assert.equal(hashToNavPath('#/c?=nameless&a=1'), '/c?a=1');
        assert.equal(
            hashToNavPath('#/c?a=1&b=2&a=3'),
            '/c?a=1&a=3&b=2',
            'a repeated key is grouped at its first position'
        );
    });

    test('canonicalNavPath matches EpicStaff and refuses what EpicStaff refuses', () => {
        assert.equal(canonicalNavPath('/'), '/');
        assert.equal(canonicalNavPath('/a%3ab/(x)'), null, '"(" is outside the grammar');
        assert.equal(canonicalNavPath('/a%3ab/%28x%29'), '/a%3Ab/%28x%29');
        assert.equal(canonicalNavPath('/a/%2e%2e/b'), null);
        assert.equal(canonicalNavPath('/bad%zz'), null);
        assert.equal(canonicalNavPath('/bad%FF'), null, 'not UTF-8');
        assert.equal(canonicalNavPath('no-slash'), null);
        assert.equal(
            canonicalNavPath('/c?b=1&10=x&2=y'),
            '/c?2=y&10=x&b=1',
            'integer-like keys first, as EpicStaff orders them'
        );
    });

    test('has no canonical form for dot segments or over-long paths', () => {
        assert.equal(hashToNavPath('#/a/../b'), null);
        assert.equal(hashToNavPath('#/a/%2e%2e/b'), null);
        assert.equal(hashToNavPath('#/./b'), null);
        assert.equal(hashToNavPath('#/' + 'a'.repeat(1100)), null);
    });
});
