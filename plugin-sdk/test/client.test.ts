import assert from 'node:assert/strict';
import { afterEach, describe, test } from 'node:test';

import { BridgeCallError, connect, type EpicStaffBridge } from '../dist/index.js';
import { createMockHost, type MockHost } from '../dist/mock-host.js';
import { delay, FakeWindow, frameWithHost, frameWithScriptedHost, waitFor } from './helpers/fake-window.ts';

const cleanups: Array<() => void> = [];
afterEach(() => {
    while (cleanups.length > 0) cleanups.pop()?.();
});

function track(bridge: EpicStaffBridge, host?: MockHost): EpicStaffBridge {
    cleanups.push(() => {
        bridge.close();
        host?.close();
    });
    return bridge;
}

function chatAdminHost(): MockHost {
    const host = createMockHost({
        plugin: { id: 'chat-admin', version: '0.1.0', name: 'Chat Admin' },
        flows: { chat: (variables) => ({ answer: `echo: ${String(variables['question'])}` }) },
        kvTables: { conversations: [{ key: 'c_1', value: { title: 'Hello', turns: 1 } }] },
        latencyMs: 0,
        closeGraceMs: 0,
    });
    cleanups.push(() => host.close());
    return host;
}

describe('connect() handshake', () => {
    test('posts {v: 2, kind: "ready"} to window.parent and resolves with the init context', async () => {
        const win = new FakeWindow();
        frameWithHost(win, chatAdminHost());

        const bridge = track(await connect({ window: win.asWindow() }));

        assert.deepEqual(win.parentFrame.posted, [{ data: { v: 2, kind: 'ready' }, targetOrigin: '*' }]);
        assert.equal(bridge.mocked, false);
        assert.deepEqual(bridge.context.plugin, { id: 'chat-admin', version: '0.1.0', name: 'Chat Admin' });
        assert.deepEqual(bridge.context.access, [
            { alias: 'chat', type: 'flow', actions: ['run', 'sessions.read', 'sessions.stop'] },
            { alias: 'conversations', type: 'key_value_table', actions: ['read'] },
        ]);
        assert.equal(bridge.context.nav.path, '/');
        assert.equal(win.messageListenerCount, 0, 'the window listener is removed after the handshake');
    });

    test('accepts init only from window.parent', async () => {
        const win = new FakeWindow();
        const host = chatAdminHost();
        const parent = win.parentFrame;
        parent.handler = (data) => {
            const result = host.handshake(data);
            assert.ok(result.ok);
            const { port1: strayPort } = new MessageChannel();
            // A message from any other window is ignored, even a well-formed init.
            win.deliverMessage(result.init, {}, [strayPort]);
            strayPort.close();
            setTimeout(() => win.deliverMessage(result.init, parent, [result.port]), 10);
        };

        const bridge = track(await connect({ window: win.asWindow() }));
        const hello = await bridge.call('bridge.hello');
        assert.equal(hello.bridge_version, 2);
    });

    test('rejects with the host error code when EpicStaff refuses the handshake', async () => {
        const win = new FakeWindow();
        const parent = win.parentFrame;
        // EpicStaff answers with its own bridge version, so the error carries v: 1 here.
        parent.handler = () =>
            queueMicrotask(() =>
                win.deliverMessage(
                    {
                        v: 1,
                        kind: 'error',
                        error: { code: 'unsupported', message: 'This plugin declares bridge version 1.' },
                    },
                    parent
                )
            );

        await assert.rejects(connect({ window: win.asWindow() }), (error: unknown) => {
            assert.ok(error instanceof BridgeCallError);
            assert.equal(error.code, 'unsupported');
            assert.equal(error.method, null);
            return true;
        });
    });

    test('times out when EpicStaff never answers, and restores history', async () => {
        const win = new FakeWindow();
        await assert.rejects(connect({ window: win.asWindow(), timeoutMs: 20 }), (error: unknown) => {
            assert.ok(error instanceof BridgeCallError);
            assert.equal(error.code, 'timeout');
            return true;
        });
        assert.equal(Object.hasOwn(win.history, 'pushState'), false);
        assert.equal(Object.hasOwn(win.history, 'replaceState'), false);
        assert.equal(win.messageListenerCount, 0);
    });

    test('returns the same bridge for every connect() on one window', async () => {
        const win = new FakeWindow();
        frameWithHost(win, chatAdminHost());

        const first = connect({ window: win.asWindow() });
        const second = connect({ window: win.asWindow() });
        assert.equal(first, second);
        track(await first);
        assert.equal(win.parentFrame.posted.length, 1, 'only one ready is posted');
    });

    test('uses the mock host when the page is not framed', async () => {
        const win = new FakeWindow({ framed: false });
        const host = chatAdminHost();

        const bridge = track(await connect({ window: win.asWindow(), mock: host }));

        assert.equal(bridge.mocked, true);
        assert.equal(bridge.context.plugin.id, 'chat-admin');
        const entry = await bridge.kv.get('conversations', 'c_1');
        assert.deepEqual(entry.value, { title: 'Hello', turns: 1 });
    });

    test('accepts a lazy mock factory and refuses when the mock is off', async () => {
        const lazy = new FakeWindow({ framed: false });
        const bridge = track(await connect({ window: lazy.asWindow(), mock: async () => chatAdminHost() }));
        assert.equal(bridge.mocked, true);

        const off = new FakeWindow({ framed: false });
        await assert.rejects(connect({ window: off.asWindow(), mock: false }), { code: 'unsupported' });
    });
});

describe('calls', () => {
    test('resolve with the result and reject with BridgeCallError carrying the host code', async () => {
        const win = new FakeWindow();
        frameWithHost(win, chatAdminHost());
        const bridge = track(await connect({ window: win.asWindow() }));

        const list = await bridge.kv.list({ table: 'conversations' });
        assert.equal(list.count, 1);

        await assert.rejects(bridge.kv.get('conversations', 'not a key'), (error: unknown) => {
            assert.ok(error instanceof BridgeCallError);
            assert.equal(error.code, 'bad_request');
            assert.equal(error.method, 'kv.get');
            return true;
        });
        await assert.rejects(bridge.kv.list({ table: 'chat' }), { code: 'forbidden' });
        await assert.rejects(bridge.kv.get('conversations', 'missing'), { code: 'not_found' });
    });

    test('time out with code "timeout" when EpicStaff does not answer', async () => {
        const win = new FakeWindow();
        frameWithScriptedHost(win, () => undefined);
        const bridge = track(await connect({ window: win.asWindow(), requestTimeoutMs: 20 }));

        await assert.rejects(bridge.call('bridge.hello'), { code: 'timeout', method: 'bridge.hello' });
    });

    test('use ids and the v2 envelope', async () => {
        const win = new FakeWindow();
        const host = frameWithScriptedHost(win, (request, scripted) => scripted.reply(request, {}));
        const bridge = track(await connect({ window: win.asWindow(), navSync: false }));

        await bridge.call('sessions.unsubscribe', { subscription: 'sub-1' });
        await bridge.call('bridge.hello');

        assert.deepEqual(host.requests, [
            { v: 2, kind: 'request', id: 1, method: 'sessions.unsubscribe', params: { subscription: 'sub-1' } },
            { v: 2, kind: 'request', id: 2, method: 'bridge.hello', params: {} },
        ]);
    });

    test('over 64 KB fail locally with bad_request and are never sent', async () => {
        const win = new FakeWindow();
        const host = frameWithScriptedHost(win, (request, scripted) => scripted.reply(request, {}));
        const bridge = track(await connect({ window: win.asWindow(), navSync: false }));

        await assert.rejects(bridge.flows.run('chat', { question: 'x'.repeat(70 * 1024) }), { code: 'bad_request' });
        assert.equal(host.requests.length, 0);
    });

    test('keep at most 10 requests in flight; the rest wait instead of failing', async () => {
        const win = new FakeWindow();
        const held: Array<() => void> = [];
        frameWithScriptedHost(win, (request, scripted) => held.push(() => scripted.reply(request, { n: request.id })));
        const bridge = track(await connect({ window: win.asWindow(), navSync: false }));

        const calls = Array.from({ length: 12 }, () => bridge.call('bridge.hello'));
        await waitFor(() => held.length === 10);
        await delay(20);
        assert.equal(held.length, 10, 'the 11th request waits for a free slot');

        held.shift()?.();
        await waitFor(() => held.length === 10);
        while (held.length > 0) held.shift()?.();
        await waitFor(() => held.length === 1);
        held.shift()?.();
        const results = await Promise.all(calls);
        assert.equal(results.length, 12);
    });

    test('are rejected with "closed" when the bridge closes', async () => {
        const win = new FakeWindow();
        frameWithScriptedHost(win, () => undefined);
        const bridge = await connect({ window: win.asWindow(), navSync: false });

        const pending = bridge.call('bridge.hello');
        bridge.close();
        await assert.rejects(pending, { code: 'closed' });
        await assert.rejects(bridge.call('bridge.hello'), { code: 'closed' });
    });
});
