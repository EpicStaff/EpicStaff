import assert from 'node:assert/strict';
import { afterEach, describe, test } from 'node:test';

import { connect, type EpicStaffBridge } from '../dist/index.js';
import { createMockHost, jsonbText, type MockHost, type MockKvEntry } from '../dist/mock-host.js';
import { FakeWindow, frameWithHost, frameWithScriptedHost } from './helpers/fake-window.ts';

const cleanups: Array<() => void> = [];
afterEach(() => {
    while (cleanups.length > 0) cleanups.pop()?.();
});

const ENTRIES: MockKvEntry[] = [
    {
        key: 'c_b',
        value: { title: 'Second', turns: 2 },
        created_at: '2026-10-01T10:00:00Z',
        updated_at: '2026-10-03T10:00:00Z',
    },
    {
        key: 'c_a',
        value: { title: 'First', turns: 1 },
        created_at: '2026-10-01T09:00:00Z',
        updated_at: '2026-10-01T09:00:00Z',
    },
    { key: 'other', value: 'x'.repeat(300), created_at: '2026-10-02T09:00:00Z', updated_at: '2026-10-02T09:00:00Z' },
];

async function connectMock(
    options: Parameters<typeof createMockHost>[0] = {}
): Promise<{ bridge: EpicStaffBridge; host: MockHost }> {
    const win = new FakeWindow();
    const host = createMockHost({
        flows: { chat: () => ({}) },
        kvTables: { conversations: ENTRIES },
        latencyMs: 0,
        closeGraceMs: 0,
        ...options,
    });
    frameWithHost(win, host);
    const bridge = await connect({ window: win.asWindow(), navSync: false });
    cleanups.push(() => {
        bridge.close();
        host.close();
    });
    return { bridge, host };
}

describe('mock host', () => {
    test('kv.list searches keys, sorts, pages and returns jsonb-style previews without ids', async () => {
        const { bridge } = await connectMock();

        const all = await bridge.kv.list({ table: 'conversations' });
        assert.equal(all.count, 3);
        assert.deepEqual(
            all.items.map((item) => item.key),
            ['c_a', 'c_b', 'other']
        );
        assert.deepEqual(Object.keys(all.items[0] ?? {}).sort(), [
            'created_at',
            'key',
            'updated_at',
            'value_preview',
            'value_truncated',
        ]);
        assert.equal(all.items[0]?.value_preview, '{"title": "First", "turns": 1}');
        assert.equal(all.items[2]?.value_truncated, true);
        assert.equal(all.items[2]?.value_preview.length, 200);

        const newest = await bridge.kv.list({
            table: 'conversations',
            search: 'C_',
            ordering: '-updated_at',
            limit: 1,
            offset: 0,
        });
        assert.equal(newest.count, 2);
        assert.deepEqual(
            newest.items.map((item) => item.key),
            ['c_b']
        );
        const page2 = await bridge.kv.list({
            table: 'conversations',
            search: 'c_',
            ordering: '-updated_at',
            limit: 1,
            offset: 1,
        });
        assert.deepEqual(
            page2.items.map((item) => item.key),
            ['c_a']
        );
    });

    test('kv.list and kv.get validate params like EpicStaff', async () => {
        const { bridge } = await connectMock();

        await assert.rejects(bridge.kv.list({ table: 'conversations', limit: 101 }), { code: 'bad_request' });
        await assert.rejects(bridge.kv.list({ table: 'conversations', offset: -1 }), { code: 'bad_request' });
        await assert.rejects(bridge.kv.list({ table: 'conversations', ordering: 'created_at' as 'key' }), {
            code: 'bad_request',
        });
        await assert.rejects(bridge.kv.list({ table: 'conversations', search: 's'.repeat(513) }), {
            code: 'bad_request',
        });
        await assert.rejects(bridge.kv.list({ table: 'chat' }), { code: 'forbidden' }, 'a flow alias is not a table');
        await assert.rejects(bridge.kv.get('conversations', '1abc'), { code: 'bad_request' });
        await assert.rejects(bridge.kv.get('conversations', 'k'.repeat(513)), { code: 'bad_request' });
        await assert.rejects(bridge.kv.get('nope', 'c_a'), { code: 'forbidden' });
        await assert.rejects(bridge.kv.get('conversations', 'c_zzz'), { code: 'not_found' });

        const entry = await bridge.kv.get('conversations', 'c_a');
        assert.deepEqual(entry, {
            key: 'c_a',
            value: { title: 'First', turns: 1 },
            created_at: '2026-10-01T09:00:00Z',
            updated_at: '2026-10-01T09:00:00Z',
        });
    });

    test('refuses unknown methods and params, and invalid nav paths', async () => {
        const { bridge } = await connectMock();
        const loose = bridge.call.bind(bridge) as (
            method: string,
            params?: Record<string, unknown>
        ) => Promise<unknown>;

        await assert.rejects(loose('kv.delete', { table: 'conversations', key: 'c_a' }), { code: 'unsupported' });
        await assert.rejects(loose('kv.get', { table: 'conversations', key: 'c_a', id: 3 }), { code: 'bad_request' });
        await assert.rejects(bridge.call('nav.changed', { path: 'no-slash' }), { code: 'bad_request' });
        await assert.rejects(bridge.call('nav.changed', { path: '/a/../b' }), { code: 'bad_request' });
        await assert.rejects(bridge.call('nav.changed', { path: '/a%zz' }), { code: 'bad_request' });
        await bridge.call('nav.changed', { path: '/conversations?search=a%20b&page=2', replace: true });
    });

    test('sessions are reachable only when this page started them', async () => {
        const { bridge } = await connectMock();
        await assert.rejects(bridge.sessions.get(999), { code: 'not_found' });

        const { session_id: sessionId } = await bridge.flows.run('chat', { question: 'q' });
        const session = await bridge.sessions.get(sessionId);
        assert.equal(session.flow, 'chat');
    });

    test('a mocked flow can write the mock tables, like the real flow writes the conversation', async () => {
        const { bridge, host } = await connectMock({
            flows: {
                chat: (variables, context) => {
                    context.kv.set('conversations', String(variables['conversation_id']), { title: 'New', turns: 1 });
                    return { answer: 'ok' };
                },
            },
        });

        await bridge.flows.runAndWait('chat', { conversation_id: 'c_new' });

        assert.deepEqual(host.kv.get('conversations', 'c_new')?.value, { title: 'New', turns: 1 });
        const list = await bridge.kv.list({ table: 'conversations', search: 'c_new' });
        assert.equal(list.count, 1);
    });

    test('answers a wrong bridge version with an error instead of init', () => {
        const host = createMockHost();
        cleanups.push(() => host.close());
        const result = host.handshake({ v: 1, kind: 'ready' });
        assert.equal(result.ok, false);
    });
});

describe('jsonbText', () => {
    test('prints like Postgres jsonb: shorter keys first, spaced separators', () => {
        assert.equal(
            jsonbText({ messages: [{ role: 'user' }], turns: 2, title: 'Hi', conversation_id: 'c_1' }),
            '{"title": "Hi", "turns": 2, "messages": [{"role": "user"}], "conversation_id": "c_1"}'
        );
        assert.equal(jsonbText(null), 'null');
        assert.equal(jsonbText([1, 'a']), '[1, "a"]');
    });
});

describe('scripted host sanity', () => {
    test('the fake frame delivers init through window.parent only', async () => {
        const win = new FakeWindow();
        frameWithScriptedHost(win, (request, host) => host.reply(request, { ok: true }));
        const bridge = await connect({ window: win.asWindow(), navSync: false });
        cleanups.push(() => bridge.close());
        assert.equal(bridge.context.plugin.id, 'scripted');
    });
});
