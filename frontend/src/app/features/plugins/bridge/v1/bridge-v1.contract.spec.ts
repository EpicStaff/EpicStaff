/**
 * Pins plugin bridge v1, a public contract: installed plugins depend on every name, key, error
 * code and HTTP call below. If this spec fails, do not update it — add a v2 table instead.
 * (Sessions became page-scoped before the bridge was released; that change was made in place.)
 */
import { HttpErrorResponse, provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { firstValueFrom, Observable, of } from 'rxjs';

import { SKIP_FORBIDDEN_RELOAD } from '../../../../core/interceptors/skip-forbidden-reload.context';
import { ActiveOrgService } from '../../../../services/auth/active-org.service';
import { SseTicketService } from '../../../../services/auth/sse-ticket.service';
import { ConfigService } from '../../../../services/config';
import { buildAccessPolicy } from '../access-policy';
import { BridgeMethodContext } from '../bridge-method';
import { BRIDGE_ERROR_CODES, BRIDGE_EVENT_TOPICS, BRIDGE_LIMITS, BridgeError, BridgeParams } from '../bridge-protocol';
import { BRIDGE_TABLES, findBridgeMethod } from '../bridge-tables';
import { PluginBridgeApiService } from '../plugin-bridge-api.service';
import { PluginBridgeHost } from '../plugin-bridge-host.service';
import { PLUGIN_EVENT_SOURCE_FACTORY } from '../plugin-session-stream';
import {
    buildUiSession,
    createPluginFrame,
    FakeEventSource,
    FakeMessageChannel,
    FakeMessagePort,
    postFromWindow,
} from '../testing/bridge-test-harness';
import { BRIDGE_V1_METHODS } from './bridge-v1.methods';

const METHOD_SHAPES = {
    'bridge.hello': { params: [], result: ['bridge_version', 'plugin', 'access', 'methods'] },
    'flows.run': { params: ['flow', 'variables'], result: ['session_id'] },
    'sessions.get': { params: ['session_id'], result: ['status', 'variables', 'flow'] },
    'sessions.subscribe': { params: ['session_id'], result: ['subscription'] },
    'sessions.unsubscribe': { params: ['subscription'], result: [] },
    'sessions.stop': { params: ['session_id'], result: [] },
};

interface FakeContext {
    context: BridgeMethodContext;
    opened: number[];
    /** Sessions the page started; only these are reachable. */
    ownSessions: Set<number>;
    closeSubscription: ReturnType<typeof vi.fn>;
    consumeRun: ReturnType<typeof vi.fn>;
    assertCanSubscribe: ReturnType<typeof vi.fn>;
}

describe('plugin bridge v1 contract', () => {
    let httpMock: HttpTestingController;
    let api: PluginBridgeApiService;

    beforeEach(() => {
        FakeEventSource.instances.length = 0;
        TestBed.configureTestingModule({
            providers: [
                provideHttpClient(),
                provideHttpClientTesting(),
                { provide: ConfigService, useValue: { apiUrl: '/api/' } },
                PluginBridgeHost,
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
        actions: ('run' | 'sessions.read' | 'sessions.stop')[] = ['run', 'sessions.read'],
        ownSessionIds: number[] = []
    ): FakeContext {
        const opened: number[] = [];
        const ownSessions = new Set(ownSessionIds);
        const closeSubscription = vi.fn((subscription: string) => subscription === 'sub-1');
        const consumeRun = vi.fn();
        const assertCanSubscribe = vi.fn();
        const context: BridgeMethodContext = {
            bridgeVersion: 1,
            plugin: { id: 'chat-bot', version: '0.1.0', name: 'Chat Bot' },
            access: buildAccessPolicy([{ alias: 'chat', type: 'flow', actions, resource_id: 42 }]),
            api,
            consumeRun,
            assertCanSubscribe,
            openSubscription: (sessionId) => {
                opened.push(sessionId);
                return `sub-${opened.length}`;
            },
            closeSubscription,
            rememberOwnSession: (sessionId) => {
                ownSessions.add(sessionId);
            },
            isOwnSession: (sessionId) => ownSessions.has(sessionId),
        };
        return { context, opened, ownSessions, closeSubscription, consumeRun, assertCanSubscribe };
    }

    function invoke(context: BridgeMethodContext, method: string, params: BridgeParams): Observable<unknown> {
        const definition = findBridgeMethod(1, method);
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
        it('serves bridge version 1 with the frozen v1 table', () => {
            expect(Object.keys(BRIDGE_TABLES)).toContain('1');
            expect(BRIDGE_TABLES[1]).toBe(BRIDGE_V1_METHODS);
            expect(Object.isFrozen(BRIDGE_V1_METHODS)).toBe(true);
        });

        it('pins the method names, their params and their result keys', () => {
            const shapes = Object.fromEntries(
                Object.entries(BRIDGE_V1_METHODS).map(([name, method]) => [
                    name,
                    { params: [...method.paramKeys], result: [...method.resultKeys] },
                ])
            );
            expect(shapes).toEqual(METHOD_SHAPES);
        });

        it('pins the error codes, event topics and limits', () => {
            expect([...BRIDGE_ERROR_CODES]).toEqual([
                'bad_request',
                'forbidden',
                'not_found',
                'rate_limited',
                'unsupported',
                'internal',
            ]);
            expect([...BRIDGE_EVENT_TOPICS]).toEqual(['session.message', 'session.status', 'subscription.closed']);
            expect(BRIDGE_LIMITS).toEqual({
                maxRequestBytes: 65536,
                maxInFlight: 10,
                maxSubscriptions: 4,
                maxRunsPerMinute: 20,
            });
        });

        it('never resolves an inherited property as a method', () => {
            for (const name of ['constructor', '__proto__', 'toString', 'hasOwnProperty']) {
                expect(findBridgeMethod(1, name)).toBeNull();
            }
            expect(findBridgeMethod(0, 'bridge.hello')).toBeNull();
        });
    });

    describe('methods', () => {
        it('bridge.hello describes the plugin, its aliases and the methods, with no ids', async () => {
            const { context } = fakeContext();

            expect(await firstValueFrom(invoke(context, 'bridge.hello', {}))).toEqual({
                bridge_version: 1,
                plugin: { id: 'chat-bot', version: '0.1.0', name: 'Chat Bot' },
                access: [{ alias: 'chat', type: 'flow', actions: ['run', 'sessions.read'] }],
                methods: Object.keys(METHOD_SHAPES),
            });
        });

        it('flows.run posts {graph_id, variables} to /api/run-session/ and returns {session_id}', async () => {
            const { context, consumeRun, ownSessions } = fakeContext();
            const result = firstValueFrom(
                invoke(context, 'flows.run', { flow: 'chat', variables: { question: 'Hi' } })
            );

            const request = httpMock.expectOne('/api/run-session/');
            expect(request.request.method).toBe('POST');
            expect(request.request.body).toEqual({ graph_id: 42, variables: { question: 'Hi' } });
            expect(request.request.context.get(SKIP_FORBIDDEN_RELOAD)).toBe(true);
            request.flush({ session_id: 9 });

            expect(await result).toEqual({ session_id: 9 });
            expect(consumeRun).toHaveBeenCalledTimes(1);
            expect([...ownSessions]).toEqual([9]);
        });

        it('flows.run makes no session reachable when the run fails', async () => {
            const { context, ownSessions } = fakeContext();
            const failed = firstValueFrom(invoke(context, 'flows.run', { flow: 'chat' })).catch(
                (error: unknown) => error
            );
            httpMock.expectOne('/api/run-session/').flush(null, { status: 403, statusText: 'Forbidden' });
            expect(await failed).toBeInstanceOf(HttpErrorResponse);

            const empty = expectBridgeError(() => invoke(context, 'flows.run', { flow: 'chat' }), 'internal');
            httpMock.expectOne('/api/run-session/').flush({ session_id: 'nine' });
            await empty;

            expect(ownSessions.size).toBe(0);
        });

        it('flows.run sends {} when no variables are given', async () => {
            const { context } = fakeContext();
            const result = firstValueFrom(invoke(context, 'flows.run', { flow: 'chat' }));

            const request = httpMock.expectOne('/api/run-session/');
            expect(request.request.body).toEqual({ graph_id: 42, variables: {} });
            request.flush({ session_id: 3 });
            expect(await result).toEqual({ session_id: 3 });
        });

        it('flows.run refuses an unknown alias, a missing grant and bad variables before any HTTP', async () => {
            await expectBridgeError(
                () => invoke(fakeContext().context, 'flows.run', { flow: 'billing', variables: {} }),
                'forbidden'
            );
            await expectBridgeError(
                () => invoke(fakeContext(['sessions.read']).context, 'flows.run', { flow: 'chat' }),
                'forbidden'
            );
            await expectBridgeError(
                () => invoke(fakeContext().context, 'flows.run', { flow: 'chat', variables: ['x'] }),
                'bad_request'
            );
            httpMock.expectNone('/api/run-session/');
        });

        it('sessions.get reads /api/sessions/{id}/ and returns {status, variables, flow}', async () => {
            const { context } = fakeContext(undefined, [9]);
            const result = firstValueFrom(invoke(context, 'sessions.get', { session_id: 9 }));

            const request = httpMock.expectOne('/api/sessions/9/');
            expect(request.request.method).toBe('GET');
            expect(request.request.context.get(SKIP_FORBIDDEN_RELOAD)).toBe(true);
            request.flush({ id: 9, graph: 42, status: 'end', variables: { answer: 'Hello' }, status_data: {} });

            expect(await result).toEqual({ status: 'end', variables: { answer: 'Hello' }, flow: 'chat' });
        });

        it.each(['sessions.get', 'sessions.subscribe', 'sessions.stop'])(
            '%s answers not_found for a session this page did not start, before any HTTP',
            async (method) => {
                const { context, opened } = fakeContext(['run', 'sessions.read', 'sessions.stop'], [8]);

                await expectBridgeError(() => invoke(context, method, { session_id: 9 }), 'not_found');

                httpMock.expectNone('/api/sessions/9/');
                httpMock.expectNone('/api/sessions/9/stop/');
                expect(opened).toEqual([]);
            }
        );

        it("a session from this page's own flows.run is then reachable", async () => {
            const { context } = fakeContext();
            const run = firstValueFrom(invoke(context, 'flows.run', { flow: 'chat' }));
            httpMock.expectOne('/api/run-session/').flush({ session_id: 9 });
            await run;

            const result = firstValueFrom(invoke(context, 'sessions.get', { session_id: 9 }));
            httpMock.expectOne('/api/sessions/9/').flush({ id: 9, graph: 42, status: 'run', variables: {} });

            expect(await result).toEqual({ status: 'run', variables: {}, flow: 'chat' });
        });

        it('sessions.get answers not_found for a session of a flow outside the access list', async () => {
            const { context } = fakeContext(undefined, [9]);
            const result = expectBridgeError(() => invoke(context, 'sessions.get', { session_id: 9 }), 'not_found');

            httpMock.expectOne('/api/sessions/9/').flush({ id: 9, graph: 77, status: 'run', variables: {} });
            await result;
        });

        it('sessions.get rejects a session id that is not a positive integer', async () => {
            for (const sessionId of ['9', 0, -1, 1.5, null]) {
                await expectBridgeError(
                    () => invoke(fakeContext().context, 'sessions.get', { session_id: sessionId }),
                    'bad_request'
                );
            }
        });

        it('sessions.subscribe checks the session, then opens a subscription', async () => {
            const { context, opened, assertCanSubscribe } = fakeContext(undefined, [9]);
            const result = firstValueFrom(invoke(context, 'sessions.subscribe', { session_id: 9 }));

            expect(assertCanSubscribe).toHaveBeenCalledTimes(1);
            httpMock.expectOne('/api/sessions/9/').flush({ id: 9, graph: 42, status: 'run', variables: {} });

            expect(await result).toEqual({ subscription: 'sub-1' });
            expect(opened).toEqual([9]);
        });

        it('sessions.subscribe opens nothing for a session of a flow outside the access list', async () => {
            const { context, opened } = fakeContext(undefined, [9]);
            const result = expectBridgeError(
                () => invoke(context, 'sessions.subscribe', { session_id: 9 }),
                'not_found'
            );

            httpMock.expectOne('/api/sessions/9/').flush({ id: 9, graph: 77, status: 'run', variables: {} });
            await result;
            expect(opened).toEqual([]);
        });

        it('sessions.unsubscribe closes an open subscription and answers not_found otherwise', async () => {
            const { context, closeSubscription } = fakeContext();

            expect(await firstValueFrom(invoke(context, 'sessions.unsubscribe', { subscription: 'sub-1' }))).toEqual(
                {}
            );
            await expectBridgeError(
                () => invoke(context, 'sessions.unsubscribe', { subscription: 'sub-9' }),
                'not_found'
            );
            expect(closeSubscription).toHaveBeenCalledWith('sub-1');
        });

        it('sessions.stop checks the session, then posts /api/sessions/{id}/stop/', async () => {
            const { context } = fakeContext(['sessions.stop'], [9]);
            const result = firstValueFrom(invoke(context, 'sessions.stop', { session_id: 9 }));

            httpMock.expectOne('/api/sessions/9/').flush({ id: 9, graph: 42, status: 'run', variables: {} });
            const stop = httpMock.expectOne('/api/sessions/9/stop/');
            expect(stop.request.method).toBe('POST');
            expect(stop.request.body).toEqual({});
            expect(stop.request.context.get(SKIP_FORBIDDEN_RELOAD)).toBe(true);
            stop.flush(null, { status: 204, statusText: 'No Content' });

            expect(await result).toEqual({});
        });

        it('sessions.stop without the sessions.stop grant fails before any HTTP', async () => {
            await expectBridgeError(
                () => invoke(fakeContext(['run', 'sessions.read']).context, 'sessions.stop', { session_id: 9 }),
                'forbidden'
            );
            httpMock.expectNone('/api/sessions/9/');
        });

        it('the stream URL carries the single-use SSE ticket', () => {
            expect(api.sessionStreamUrl(9, 'a b')).toBe('/api/run-session/subscribe/9/?ticket=a%20b');
        });
    });

    describe('envelope', () => {
        beforeEach(() => vi.stubGlobal('MessageChannel', FakeMessageChannel));

        afterEach(() => {
            vi.unstubAllGlobals();
            document.body.innerHTML = '';
        });

        function connect(): FakeMessagePort {
            const host = TestBed.inject(PluginBridgeHost);
            const { frame, frameWindow, posted } = createPluginFrame();
            host.attach(frame, buildUiSession());
            postFromWindow(frameWindow, { v: 1, kind: 'ready' });

            expect(posted).toHaveLength(1);
            const [{ message, targetOrigin, transfer }] = posted;
            expect(message).toEqual({
                v: 1,
                kind: 'init',
                context: {
                    plugin: { id: 'chat-bot', version: '0.1.0', name: 'Chat Bot' },
                    access: [{ alias: 'chat', type: 'flow', actions: ['run', 'sessions.read', 'sessions.stop'] }],
                },
            });
            expect(targetOrigin).toBe('*');
            expect(transfer).toHaveLength(1);
            expect(transfer[0]).toBeInstanceOf(FakeMessagePort);
            return transfer[0] as FakeMessagePort;
        }

        it('answers a failure with {v, kind: "response", id, ok: false, error: {code, message}}', () => {
            const plugin = connect();

            plugin.postMessage({ v: 1, kind: 'request', id: 'a1', method: 'sessions.unsubscribe', params: {} });

            expect(plugin.received).toEqual([
                {
                    v: 1,
                    kind: 'response',
                    id: 'a1',
                    ok: false,
                    error: { code: 'bad_request', message: '"subscription" must be a subscription id.' },
                },
            ]);
        });

        it('answers success as {v, kind: "response", id, ok: true, result}', () => {
            const plugin = connect();

            plugin.postMessage({ v: 1, kind: 'request', id: 7, method: 'bridge.hello' });

            expect(plugin.received).toHaveLength(1);
            expect(plugin.received[0]).toMatchObject({ v: 1, kind: 'response', id: 7, ok: true });
            expect(Object.keys(plugin.received[0] as object).sort()).toEqual(['id', 'kind', 'ok', 'result', 'v']);
        });

        it('sends subscription events as {v, kind: "event", topic, subscription, data}', async () => {
            const plugin = connect();
            plugin.postMessage({ v: 1, kind: 'request', id: 0, method: 'flows.run', params: { flow: 'chat' } });
            httpMock.expectOne('/api/run-session/').flush({ session_id: 9 });
            plugin.received.length = 0;
            plugin.postMessage({
                v: 1,
                kind: 'request',
                id: 1,
                method: 'sessions.subscribe',
                params: { session_id: 9 },
            });
            httpMock.expectOne('/api/sessions/9/').flush({ id: 9, graph: 42, status: 'run', variables: {} });
            await Promise.resolve();

            const stream = FakeEventSource.instances[0];
            expect(stream.url).toBe('/api/run-session/subscribe/9/?ticket=ticket-1');
            stream.emit('messages', {
                session_id: 9,
                uuid: 'u1',
                name: '',
                created_at: '2026-10-07T10:00:00Z',
                message_data: { message_type: 'graph_end', end_node_result: { answer: 'Hello' } },
            });
            stream.emit('status', { session_id: 9, status: 'run', status_data: { secret: 'not relayed' } });

            expect(plugin.received).toEqual([
                { v: 1, kind: 'response', id: 1, ok: true, result: { subscription: 'sub-1' } },
                {
                    v: 1,
                    kind: 'event',
                    topic: 'session.message',
                    subscription: 'sub-1',
                    data: {
                        message_type: 'graph_end',
                        name: '',
                        created_at: '2026-10-07T10:00:00Z',
                        message_data: { message_type: 'graph_end', end_node_result: { answer: 'Hello' } },
                    },
                },
                { v: 1, kind: 'event', topic: 'session.status', subscription: 'sub-1', data: { status: 'run' } },
            ]);
        });
    });
});
