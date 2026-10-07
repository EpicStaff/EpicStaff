/**
 * Pins plugin bridge v2, a public contract: installed plugins depend on every name, key, error
 * code and HTTP call below. Once v2 is released, do not update this spec — add a v3 table instead.
 */
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { signal, WritableSignal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { firstValueFrom, Observable, of } from 'rxjs';

import { SKIP_FORBIDDEN_RELOAD } from '../../../../core/interceptors/skip-forbidden-reload.context';
import { ActiveOrgService } from '../../../../services/auth/active-org.service';
import { SseTicketService } from '../../../../services/auth/sse-ticket.service';
import { ConfigService } from '../../../../services/config';
import { PluginUiSessionAccessEntry } from '../../models/plugin.model';
import { PluginHostThemeService } from '../../services/plugin-host-theme.service';
import { buildAccessPolicy } from '../access-policy';
import { BridgeMethodContextV2 } from '../bridge-method';
import {
    BRIDGE_EVENT_TOPICS,
    BRIDGE_V2_EVENT_TOPICS,
    BRIDGE_V2_LIMITS,
    BridgeError,
    BridgeParams,
    BridgeTheme,
} from '../bridge-protocol';
import { BRIDGE_TABLES, findBridgeMethod } from '../bridge-tables';
import { PluginBridgeApiService } from '../plugin-bridge-api.service';
import { PluginBridgeHost } from '../plugin-bridge-host.service';
import { PLUGIN_EVENT_SOURCE_FACTORY } from '../plugin-session-stream';
import {
    buildUiSessionV2,
    createPluginFrame,
    FakeEventSource,
    FakeMessageChannel,
    FakeMessagePort,
    postFromWindow,
} from '../testing/bridge-test-harness';
import { BRIDGE_V1_METHODS } from '../v1/bridge-v1.methods';
import { BRIDGE_V2_METHODS } from './bridge-v2.methods';

const METHOD_SHAPES = {
    'bridge.hello': { params: [], result: ['bridge_version', 'plugin', 'access', 'methods'] },
    'flows.run': { params: ['flow', 'variables'], result: ['session_id'] },
    'sessions.get': { params: ['session_id'], result: ['status', 'variables', 'flow'] },
    'sessions.subscribe': { params: ['session_id'], result: ['subscription'] },
    'sessions.unsubscribe': { params: ['subscription'], result: [] },
    'sessions.stop': { params: ['session_id'], result: [] },
    'kv.list': { params: ['table', 'search', 'ordering', 'limit', 'offset'], result: ['count', 'items'] },
    'kv.get': { params: ['table', 'key'], result: ['key', 'value', 'created_at', 'updated_at'] },
    'nav.changed': { params: ['path', 'replace'], result: [] },
};

const ENTRIES_URL = '/api/key-value-table-entries/';

/** A list row as the API returns it, ids and all. */
function listRow(key: string, table = 5): Record<string, unknown> {
    return {
        id: 31,
        table,
        key,
        value_preview: '{"title": "Hi"}',
        value_truncated: false,
        created_at: '2026-10-07T10:00:00Z',
        updated_at: '2026-10-07T11:00:00Z',
        updated_by_session: 77,
        updated_by_graph: 42,
        updated_by_graph_name: 'Chat Admin',
    };
}

interface FakeContext {
    context: BridgeMethodContextV2;
    consumeNavigation: ReturnType<typeof vi.fn>;
    reportNavigation: ReturnType<typeof vi.fn>;
}

describe('plugin bridge v2 contract', () => {
    let httpMock: HttpTestingController;
    let api: PluginBridgeApiService;
    let theme: WritableSignal<BridgeTheme>;

    beforeEach(() => {
        FakeEventSource.instances.length = 0;
        theme = signal<BridgeTheme>({ mode: 'dark', tokens: { '--es-color-background': '#1e1f22' } });
        TestBed.configureTestingModule({
            providers: [
                provideHttpClient(),
                provideHttpClientTesting(),
                PluginBridgeHost,
                { provide: PluginHostThemeService, useValue: { theme } },
                { provide: ConfigService, useValue: { apiUrl: '/api/' } },
                { provide: ActiveOrgService, useValue: { activeOrgId: signal(1) } },
                { provide: SseTicketService, useValue: { fetchTicket: () => of('ticket-1') } },
                { provide: PLUGIN_EVENT_SOURCE_FACTORY, useValue: (url: string) => new FakeEventSource(url) },
            ],
        });
        httpMock = TestBed.inject(HttpTestingController);
        api = TestBed.inject(PluginBridgeApiService);
    });

    afterEach(() => httpMock.verify());

    function fakeContext(
        access: PluginUiSessionAccessEntry[] = [
            { alias: 'chat', type: 'flow', actions: ['run', 'sessions.read'], resource_id: 42 },
            { alias: 'conversations', type: 'key_value_table', actions: ['read'], resource_id: 5 },
        ]
    ): FakeContext {
        const consumeNavigation = vi.fn();
        const reportNavigation = vi.fn();
        const context: BridgeMethodContextV2 = {
            bridgeVersion: 2,
            plugin: { id: 'chat-admin', version: '0.2.0', name: 'Chat Admin' },
            access: buildAccessPolicy(access, 2),
            api,
            consumeRun: vi.fn(),
            assertCanSubscribe: vi.fn(),
            openSubscription: () => 'sub-1',
            closeSubscription: () => false,
            rememberOwnSession: vi.fn(),
            isOwnSession: () => false,
            consumeNavigation,
            reportNavigation,
        };
        return { context, consumeNavigation, reportNavigation };
    }

    function invoke(context: BridgeMethodContextV2, method: string, params: BridgeParams): Observable<unknown> {
        const definition = findBridgeMethod(2, method);
        if (!definition) throw new Error(`no method ${method}`);
        return definition.invoke(context, params);
    }

    async function expectBridgeError(run: () => Observable<unknown>, code: string): Promise<void> {
        let thrown: unknown = null;
        try {
            await firstValueFrom(run());
        } catch (error) {
            thrown = error;
        }
        expect(thrown).toBeInstanceOf(BridgeError);
        expect((thrown as BridgeError).code).toBe(code);
    }

    describe('surface', () => {
        it('serves bridge version 2 with its own frozen table, next to v1', () => {
            expect(Object.keys(BRIDGE_TABLES)).toEqual(['1', '2']);
            expect(BRIDGE_TABLES[1]).toBe(BRIDGE_V1_METHODS);
            expect(BRIDGE_TABLES[2]).toBe(BRIDGE_V2_METHODS);
            expect(Object.isFrozen(BRIDGE_V2_METHODS)).toBe(true);
        });

        it('pins the method names, their params and their result keys', () => {
            const shapes = Object.fromEntries(
                Object.entries(BRIDGE_V2_METHODS).map(([name, method]) => [
                    name,
                    { params: [...method.paramKeys], result: [...method.resultKeys] },
                ])
            );
            expect(shapes).toEqual(METHOD_SHAPES);
        });

        it('serves the v1 flow and session methods unchanged: the very same definitions', () => {
            for (const name of [
                'flows.run',
                'sessions.get',
                'sessions.subscribe',
                'sessions.unsubscribe',
                'sessions.stop',
            ] as const) {
                expect(BRIDGE_V2_METHODS[name]).toBe(BRIDGE_V1_METHODS[name]);
            }
        });

        it('pins the event topics and the v2 limits, and leaves the v1 topics alone', () => {
            expect([...BRIDGE_EVENT_TOPICS]).toEqual(['session.message', 'session.status', 'subscription.closed']);
            expect([...BRIDGE_V2_EVENT_TOPICS]).toEqual([
                'session.message',
                'session.status',
                'subscription.closed',
                'nav.navigate',
                'theme.changed',
            ]);
            expect(BRIDGE_V2_LIMITS).toEqual({
                maxNavChangesPerMinute: 120,
                maxNavPathLength: 1024,
                maxKeyValueTextLength: 512,
                maxKeyValuePageSize: 100,
                defaultKeyValuePageSize: 20,
            });
        });

        it('never resolves an inherited property as a method', () => {
            for (const name of ['constructor', '__proto__', 'toString', 'hasOwnProperty']) {
                expect(findBridgeMethod(2, name)).toBeNull();
            }
            expect(findBridgeMethod(3, 'bridge.hello')).toBeNull();
        });
    });

    describe('bridge.hello', () => {
        it('lists the v2 methods and the key-value table alias, with no ids', async () => {
            const { context } = fakeContext();

            expect(await firstValueFrom(invoke(context, 'bridge.hello', {}))).toEqual({
                bridge_version: 2,
                plugin: { id: 'chat-admin', version: '0.2.0', name: 'Chat Admin' },
                access: [
                    { alias: 'chat', type: 'flow', actions: ['run', 'sessions.read'] },
                    { alias: 'conversations', type: 'key_value_table', actions: ['read'] },
                ],
                methods: Object.keys(METHOD_SHAPES),
            });
        });
    });

    describe('kv.list', () => {
        it('lists with the defaults: GET ?table=<id>&ordering=key&limit=20&offset=0', async () => {
            const { context } = fakeContext();
            const result = firstValueFrom(invoke(context, 'kv.list', { table: 'conversations' }));

            const request = httpMock.expectOne(`${ENTRIES_URL}?table=5&ordering=key&limit=20&offset=0`);
            expect(request.request.method).toBe('GET');
            expect(request.request.context.get(SKIP_FORBIDDEN_RELOAD)).toBe(true);
            request.flush({ count: 1, next: null, previous: null, results: [listRow('c_1')] });

            expect(await result).toEqual({
                count: 1,
                items: [
                    {
                        key: 'c_1',
                        value_preview: '{"title": "Hi"}',
                        value_truncated: false,
                        created_at: '2026-10-07T10:00:00Z',
                        updated_at: '2026-10-07T11:00:00Z',
                    },
                ],
            });
        });

        it('passes search, ordering, limit and offset, in that query order', async () => {
            const { context } = fakeContext();
            const result = firstValueFrom(
                invoke(context, 'kv.list', {
                    table: 'conversations',
                    search: 'c_ab',
                    ordering: '-updated_at',
                    limit: 100,
                    offset: 40,
                })
            );

            httpMock
                .expectOne(`${ENTRIES_URL}?table=5&ordering=-updated_at&limit=100&offset=40&search=c_ab`)
                .flush({ count: 0, results: [] });

            expect(await result).toEqual({ count: 0, items: [] });
        });

        it('drops a row of another table and strips ids and who wrote each row', async () => {
            const { context } = fakeContext();
            const result = firstValueFrom(invoke(context, 'kv.list', { table: 'conversations' }));

            httpMock
                .expectOne(`${ENTRIES_URL}?table=5&ordering=key&limit=20&offset=0`)
                .flush({ count: 2, results: [listRow('c_1'), listRow('secret', 6)] });

            const { items } = (await result) as { items: Record<string, unknown>[] };
            expect(items.map((item) => item['key'])).toEqual(['c_1']);
            expect(Object.keys(items[0]).sort()).toEqual([
                'created_at',
                'key',
                'updated_at',
                'value_preview',
                'value_truncated',
            ]);
        });

        it.each([
            ['a search over 512 characters', { search: 'x'.repeat(513) }],
            ['a search that is not text', { search: 42 }],
            ['an unknown ordering', { ordering: 'value' }],
            ['ordering by session', { ordering: 'session' }],
            ['a limit of 0', { limit: 0 }],
            ['a limit over 100', { limit: 101 }],
            ['a fractional limit', { limit: 1.5 }],
            ['a limit as text', { limit: '20' }],
            ['a negative offset', { offset: -1 }],
        ])('answers bad_request for %s, before any HTTP', async (_label, params) => {
            await expectBridgeError(
                () => invoke(fakeContext().context, 'kv.list', { table: 'conversations', ...params }),
                'bad_request'
            );
            httpMock.expectNone(() => true);
        });

        it('answers forbidden for a flow alias, an unknown alias or a table without read, before any HTTP', async () => {
            await expectBridgeError(() => invoke(fakeContext().context, 'kv.list', { table: 'chat' }), 'forbidden');
            await expectBridgeError(() => invoke(fakeContext().context, 'kv.list', { table: 'billing' }), 'forbidden');
            await expectBridgeError(() => invoke(fakeContext().context, 'kv.list', {}), 'forbidden');
            const noRead = fakeContext([
                { alias: 'conversations', type: 'key_value_table', actions: ['run'], resource_id: 5 },
            ]);
            await expectBridgeError(() => invoke(noRead.context, 'kv.list', { table: 'conversations' }), 'forbidden');
            httpMock.expectNone(() => true);
        });
    });

    describe('kv.get', () => {
        it('looks the key up in the table, then reads that entry: two exact GETs, no ids returned', async () => {
            const { context } = fakeContext();
            const result = firstValueFrom(invoke(context, 'kv.get', { table: 'conversations', key: 'c_1' }));

            const lookup = httpMock.expectOne(`${ENTRIES_URL}?table=5&key=c_1&limit=1`);
            expect(lookup.request.method).toBe('GET');
            expect(lookup.request.context.get(SKIP_FORBIDDEN_RELOAD)).toBe(true);
            lookup.flush({ count: 1, results: [listRow('c_1')] });
            const read = httpMock.expectOne(`${ENTRIES_URL}31/`);
            expect(read.request.method).toBe('GET');
            expect(read.request.context.get(SKIP_FORBIDDEN_RELOAD)).toBe(true);
            read.flush({
                id: 31,
                table: 5,
                key: 'c_1',
                value: { title: 'Hi', turns: 1 },
                created_at: '2026-10-07T10:00:00Z',
                updated_at: '2026-10-07T11:00:00Z',
                updated_by_session: 77,
            });

            expect(await result).toEqual({
                key: 'c_1',
                value: { title: 'Hi', turns: 1 },
                created_at: '2026-10-07T10:00:00Z',
                updated_at: '2026-10-07T11:00:00Z',
            });
        });

        it('answers not_found when the key is not in the table, with no second request', async () => {
            const { context } = fakeContext();
            const result = expectBridgeError(
                () => invoke(context, 'kv.get', { table: 'conversations', key: 'c_2' }),
                'not_found'
            );

            httpMock.expectOne(`${ENTRIES_URL}?table=5&key=c_2&limit=1`).flush({ count: 0, results: [] });
            await result;
        });

        it('answers not_found when the lookup returns a row of another table or key, with no second request', async () => {
            const otherTable = expectBridgeError(
                () => invoke(fakeContext().context, 'kv.get', { table: 'conversations', key: 'c_1' }),
                'not_found'
            );
            httpMock
                .expectOne(`${ENTRIES_URL}?table=5&key=c_1&limit=1`)
                .flush({ count: 1, results: [listRow('c_1', 6)] });
            await otherTable;

            // A server without the exact `key` filter would return the table's first row.
            const otherKey = expectBridgeError(
                () => invoke(fakeContext().context, 'kv.get', { table: 'conversations', key: 'c_1' }),
                'not_found'
            );
            httpMock
                .expectOne(`${ENTRIES_URL}?table=5&key=c_1&limit=1`)
                .flush({ count: 9, results: [listRow('a_first')] });
            await otherKey;
        });

        it.each([
            ['another table', { table: 6, key: 'c_1' }],
            ['another key', { table: 5, key: 'c_9' }],
        ])('answers not_found when the entry read belongs to %s', async (_label, entry) => {
            const result = expectBridgeError(
                () => invoke(fakeContext().context, 'kv.get', { table: 'conversations', key: 'c_1' }),
                'not_found'
            );

            httpMock.expectOne(`${ENTRIES_URL}?table=5&key=c_1&limit=1`).flush({ results: [listRow('c_1')] });
            httpMock.expectOne(`${ENTRIES_URL}31/`).flush({ id: 31, value: 'x', ...entry });
            await result;
        });

        it.each([
            ['a key starting with a digit', '1abc'],
            ['a key with a dash', 'c-1'],
            ['a key with a slash', '../1'],
            ['an empty key', ''],
            ['a key over 512 characters', `k${'x'.repeat(512)}`],
            ['a key that is not text', 42],
        ])('answers bad_request for %s, before any HTTP', async (_label, key) => {
            await expectBridgeError(
                () => invoke(fakeContext().context, 'kv.get', { table: 'conversations', key }),
                'bad_request'
            );
            httpMock.expectNone(() => true);
        });

        it('answers forbidden for a flow alias or an unknown alias, before any HTTP', async () => {
            await expectBridgeError(
                () => invoke(fakeContext().context, 'kv.get', { table: 'chat', key: 'c_1' }),
                'forbidden'
            );
            await expectBridgeError(
                () => invoke(fakeContext().context, 'kv.get', { table: 'billing', key: 'c_1' }),
                'forbidden'
            );
            httpMock.expectNone(() => true);
        });
    });

    describe('nav.changed', () => {
        it('reports the canonical path and whether to replace, then answers {}', async () => {
            const { context, consumeNavigation, reportNavigation } = fakeContext();

            expect(
                await firstValueFrom(invoke(context, 'nav.changed', { path: '/conversations?search=a+b&page=2' }))
            ).toEqual({});
            expect(
                await firstValueFrom(invoke(context, 'nav.changed', { path: '/conversations/c_1', replace: true }))
            ).toEqual({});

            expect(reportNavigation.mock.calls).toEqual([
                ['/conversations?search=a%20b&page=2', false],
                ['/conversations/c_1', true],
            ]);
            expect(consumeNavigation).toHaveBeenCalledTimes(2);
        });

        it.each([
            ['a relative path', 'conversations'],
            ['a fragment', '/conversations#top'],
            ['a dot segment', '/a/../b'],
            ['an encoded dot segment', '/a/%2e%2e/b'],
            ['a single dot', '/.'],
            ['an empty segment', '/a//b'],
            ['a bad escape', '/a%zz'],
            ['an invalid UTF-8 escape', '/a%C0'],
            ['a space', '/a b'],
            ['a path over 1024 characters', `/${'a'.repeat(1024)}`],
            ['a scheme', 'javascript:alert(1)'],
            ['a protocol-relative URL', '//evil.example/x'],
            ['a non-string', 42],
        ])('answers bad_request for %s, without reporting it', async (_label, path) => {
            const { context, consumeNavigation, reportNavigation } = fakeContext();

            await expectBridgeError(() => invoke(context, 'nav.changed', { path }), 'bad_request');

            expect(reportNavigation).not.toHaveBeenCalled();
            expect(consumeNavigation).not.toHaveBeenCalled();
        });

        it('answers bad_request when replace is not a boolean', async () => {
            const { context, reportNavigation } = fakeContext();

            await expectBridgeError(() => invoke(context, 'nav.changed', { path: '/', replace: 'yes' }), 'bad_request');
            expect(reportNavigation).not.toHaveBeenCalled();
        });

        it('passes the rate limit error through without reporting', async () => {
            const { context, consumeNavigation, reportNavigation } = fakeContext();
            consumeNavigation.mockImplementation(() => {
                throw new BridgeError('rate_limited', 'slow down');
            });

            await expectBridgeError(() => invoke(context, 'nav.changed', { path: '/a' }), 'rate_limited');
            expect(reportNavigation).not.toHaveBeenCalled();
        });
    });

    describe('envelope and host events', () => {
        let pluginFrame: ReturnType<typeof createPluginFrame>;

        beforeEach(() => {
            vi.stubGlobal('MessageChannel', FakeMessageChannel);
            pluginFrame = createPluginFrame();
        });

        afterEach(() => {
            vi.unstubAllGlobals();
            vi.useRealTimers();
            document.body.innerHTML = '';
        });

        function connect(onNavChanged = vi.fn()): { host: PluginBridgeHost; page: FakeMessagePort } {
            const host = TestBed.inject(PluginBridgeHost);
            host.attach(pluginFrame.frame, buildUiSessionV2(), { initialPath: '/conversations/c_1', onNavChanged });
            postFromWindow(pluginFrame.frameWindow, { v: 2, kind: 'ready' });
            const page = pluginFrame.posted.at(-1)?.transfer[0];
            if (!(page instanceof FakeMessagePort)) throw new Error('no port was transferred');
            return { host, page };
        }

        it('sends init with the plugin, aliases, the path and the theme, and no ids', () => {
            connect();

            expect(pluginFrame.posted).toHaveLength(1);
            expect(pluginFrame.posted[0].message).toEqual({
                v: 2,
                kind: 'init',
                context: {
                    plugin: { id: 'chat-admin', version: '0.2.0', name: 'Chat Admin' },
                    access: [
                        { alias: 'chat', type: 'flow', actions: ['run', 'sessions.read', 'sessions.stop'] },
                        { alias: 'conversations', type: 'key_value_table', actions: ['read'] },
                    ],
                    nav: { path: '/conversations/c_1' },
                    theme: { mode: 'dark', tokens: { '--es-color-background': '#1e1f22' } },
                },
            });
        });

        it('pushes theme.changed with subscription null when the theme changes', () => {
            const { page } = connect();

            theme.set({ mode: 'light', tokens: { '--es-color-background': '#f8fafc' } });
            TestBed.tick();

            expect(page.received).toEqual([
                {
                    v: 2,
                    kind: 'event',
                    topic: 'theme.changed',
                    subscription: null,
                    data: { mode: 'light', tokens: { '--es-color-background': '#f8fafc' } },
                },
            ]);
        });

        it('pushes nav.navigate with subscription null for a new address, and nothing for the current one', () => {
            const { host, page } = connect();

            host.notifyNavigation('/conversations/c_1');
            host.notifyNavigation('/conversations?search=a+b');

            expect(page.received).toEqual([
                {
                    v: 2,
                    kind: 'event',
                    topic: 'nav.navigate',
                    subscription: null,
                    data: { path: '/conversations?search=a%20b' },
                },
            ]);
        });

        it('hands nav.changed to the host page and never echoes it back as nav.navigate', () => {
            const onNavChanged = vi.fn();
            const { host, page } = connect(onNavChanged);

            page.postMessage({ v: 2, kind: 'request', id: 1, method: 'nav.changed', params: { path: '/about' } });
            host.notifyNavigation('/about');

            expect(onNavChanged).toHaveBeenCalledWith('/about', false);
            expect(page.received).toEqual([{ v: 2, kind: 'response', id: 1, ok: true, result: {} }]);
        });

        it('answers rate_limited past 120 nav.changed a minute, and allows them again a minute later', () => {
            vi.useFakeTimers({ toFake: ['Date'] });
            vi.setSystemTime(new Date('2026-10-07T10:00:00Z'));
            const onNavChanged = vi.fn();
            const { page } = connect(onNavChanged);

            for (let id = 1; id <= BRIDGE_V2_LIMITS.maxNavChangesPerMinute + 1; id++) {
                page.postMessage({ v: 2, kind: 'request', id, method: 'nav.changed', params: { path: `/p${id}` } });
            }
            expect(page.received.at(-1)).toMatchObject({ id: 121, ok: false, error: { code: 'rate_limited' } });
            expect(onNavChanged).toHaveBeenCalledTimes(BRIDGE_V2_LIMITS.maxNavChangesPerMinute);

            vi.setSystemTime(new Date('2026-10-07T10:01:00.001Z'));
            page.postMessage({ v: 2, kind: 'request', id: 200, method: 'nav.changed', params: { path: '/again' } });
            expect(page.received.at(-1)).toMatchObject({ id: 200, ok: true });
        });

        it('answers a v1 request on a v2 page with unsupported', () => {
            const { page } = connect();

            page.postMessage({ v: 1, kind: 'request', id: 1, method: 'bridge.hello' });

            expect(page.received.at(-1)).toMatchObject({ id: 1, ok: false, error: { code: 'unsupported' } });
        });
    });
});
