import { HttpErrorResponse, provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { signal, WritableSignal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { of } from 'rxjs';

import { ActiveOrgService } from '../../../services/auth/active-org.service';
import { SseTicketService } from '../../../services/auth/sse-ticket.service';
import { ConfigService } from '../../../services/config';
import { BRIDGE_LIMITS } from './bridge-protocol';
import { PluginBridgeHost, toBridgeError } from './plugin-bridge-host.service';
import { PLUGIN_EVENT_SOURCE_FACTORY } from './plugin-session-stream';
import {
    buildUiSession,
    createPluginFrame,
    FakeEventSource,
    FakeMessageChannel,
    FakeMessagePort,
    PluginFrame,
    postFromWindow,
} from './testing/bridge-test-harness';

interface ErrorResponse {
    id: unknown;
    ok: false;
    error: { code: string; message: string };
}

describe('PluginBridgeHost', () => {
    let host: PluginBridgeHost;
    let httpMock: HttpTestingController;
    let activeOrgId: WritableSignal<number | null>;
    let pluginFrame: PluginFrame;

    beforeEach(() => {
        vi.stubGlobal('MessageChannel', FakeMessageChannel);
        FakeEventSource.instances.length = 0;
        activeOrgId = signal<number | null>(1);
        TestBed.configureTestingModule({
            providers: [
                PluginBridgeHost,
                provideHttpClient(),
                provideHttpClientTesting(),
                { provide: ConfigService, useValue: { apiUrl: '/api/' } },
                { provide: ActiveOrgService, useValue: { activeOrgId } },
                { provide: SseTicketService, useValue: { fetchTicket: () => of('ticket-1') } },
                { provide: PLUGIN_EVENT_SOURCE_FACTORY, useValue: (url: string) => new FakeEventSource(url) },
            ],
        });
        host = TestBed.inject(PluginBridgeHost);
        httpMock = TestBed.inject(HttpTestingController);
        pluginFrame = createPluginFrame();
    });

    afterEach(() => {
        host.detach();
        vi.unstubAllGlobals();
        vi.useRealTimers();
        document.body.innerHTML = '';
    });

    /** Attaches, completes the handshake and returns the plugin's end of the port. */
    function connect(session = buildUiSession()): FakeMessagePort {
        host.attach(pluginFrame.frame, session);
        postFromWindow(pluginFrame.frameWindow, { v: session.bridge_version, kind: 'ready' });
        const init = pluginFrame.posted.at(-1);
        const port = init?.transfer[0];
        if (!(port instanceof FakeMessagePort)) throw new Error('no port was transferred');
        return port;
    }

    function lastError(port: FakeMessagePort): ErrorResponse {
        return port.received.at(-1) as ErrorResponse;
    }

    /** Runs the flow from the page; the session id the server returns becomes reachable for that page. */
    function startSession(port: FakeMessagePort, sessionId: number): void {
        port.postMessage({
            v: 1,
            kind: 'request',
            id: `run-${sessionId}`,
            method: 'flows.run',
            params: { flow: 'chat' },
        });
        httpMock.expectOne('/api/run-session/').flush({ session_id: sessionId });
    }

    function subscribe(port: FakeMessagePort, id: number, sessionId: number): void {
        port.postMessage({
            v: 1,
            kind: 'request',
            id,
            method: 'sessions.subscribe',
            params: { session_id: sessionId },
        });
        httpMock.expectOne(`/api/sessions/${sessionId}/`).flush({ id: sessionId, graph: 42, status: 'run' });
    }

    describe('handshake', () => {
        it('answers ready from the plugin frame with init and a port', () => {
            connect();

            expect(pluginFrame.posted).toHaveLength(1);
            expect(pluginFrame.posted[0].message).toMatchObject({ v: 1, kind: 'init' });
            expect(host.connected()).toBe(true);
        });

        it('ignores a message whose event.source is not the plugin frame', () => {
            host.attach(pluginFrame.frame, buildUiSession());
            const other = createPluginFrame();

            postFromWindow(window, { v: 1, kind: 'ready' });
            postFromWindow(other.frameWindow, { v: 1, kind: 'ready' });
            postFromWindow(null, { v: 1, kind: 'ready' });

            expect(pluginFrame.posted).toEqual([]);
            expect(other.posted).toEqual([]);
            expect(host.connected()).toBe(false);
        });

        it('ignores a ready from the frame unless its origin is opaque ("null")', () => {
            host.attach(pluginFrame.frame, buildUiSession());

            postFromWindow(pluginFrame.frameWindow, { v: 1, kind: 'ready' }, window.location.origin);
            postFromWindow(pluginFrame.frameWindow, { v: 1, kind: 'ready' }, 'https://evil.example');

            expect(pluginFrame.posted).toEqual([]);
        });

        it('completes the handshake only once', () => {
            connect();

            postFromWindow(pluginFrame.frameWindow, { v: 1, kind: 'ready' });

            expect(pluginFrame.posted).toHaveLength(1);
        });

        it('answers a ready with the wrong version with an error and no port', () => {
            host.attach(pluginFrame.frame, buildUiSession());

            postFromWindow(pluginFrame.frameWindow, { v: 2, kind: 'ready' });

            expect(pluginFrame.posted).toHaveLength(1);
            expect(pluginFrame.posted[0].message).toMatchObject({
                v: 1,
                kind: 'error',
                error: { code: 'unsupported' },
            });
            expect(pluginFrame.posted[0].transfer).toEqual([]);
            expect(host.connected()).toBe(false);
        });

        it('stops listening once detached', () => {
            host.attach(pluginFrame.frame, buildUiSession());
            host.detach();

            postFromWindow(pluginFrame.frameWindow, { v: 1, kind: 'ready' });

            expect(pluginFrame.posted).toEqual([]);
        });
    });

    describe('requests', () => {
        it('answers a request with the wrong version with unsupported', () => {
            const port = connect();

            port.postMessage({ v: 2, kind: 'request', id: 1, method: 'bridge.hello' });

            expect(lastError(port)).toMatchObject({ id: 1, ok: false, error: { code: 'unsupported' } });
        });

        it('answers an unknown method with unsupported and an unknown param with bad_request', () => {
            const port = connect();

            port.postMessage({ v: 1, kind: 'request', id: 1, method: 'flows.delete', params: {} });
            expect(lastError(port).error.code).toBe('unsupported');

            port.postMessage({
                v: 1,
                kind: 'request',
                id: 2,
                method: 'flows.run',
                params: { flow: 'chat', graph_id: 1 },
            });
            expect(lastError(port)).toMatchObject({ id: 2, error: { code: 'bad_request' } });
            httpMock.expectNone('/api/run-session/');
        });

        it('rejects malformed envelopes and drops messages without a usable id', () => {
            const port = connect();

            port.postMessage({ v: 1, kind: 'request', method: 'bridge.hello' });
            port.postMessage({ v: 1, kind: 'request', id: { nested: true }, method: 'bridge.hello' });
            expect(port.received).toEqual([]);

            port.postMessage({ v: 1, kind: 'request', id: 1, method: 'bridge.hello', extra: true });
            expect(lastError(port).error.code).toBe('bad_request');
            port.postMessage({ v: 1, kind: 'request', id: 2, method: 'bridge.hello', params: [] });
            expect(lastError(port).error.code).toBe('bad_request');
            port.postMessage({ v: 1, id: 3, method: 'bridge.hello' });
            expect(lastError(port).error.code).toBe('bad_request');
        });

        it('forbids an ungranted alias before any HTTP', () => {
            const port = connect(
                buildUiSession({
                    access: [{ alias: 'chat', type: 'flow', actions: ['sessions.read'], resource_id: 42 }],
                })
            );

            port.postMessage({ v: 1, kind: 'request', id: 1, method: 'flows.run', params: { flow: 'chat' } });
            port.postMessage({ v: 1, kind: 'request', id: 2, method: 'flows.run', params: { flow: 'other' } });

            expect(port.received).toMatchObject([
                { id: 1, error: { code: 'forbidden' } },
                { id: 2, error: { code: 'forbidden' } },
            ]);
            httpMock.expectNone('/api/run-session/');
        });

        it('maps an HTTP 403 to forbidden without passing the server body through', () => {
            const port = connect();

            port.postMessage({ v: 1, kind: 'request', id: 1, method: 'flows.run', params: { flow: 'chat' } });
            httpMock
                .expectOne('/api/run-session/')
                .flush({ message: 'internal detail' }, { status: 403, statusText: 'Forbidden' });

            expect(lastError(port)).toEqual({
                v: 1,
                kind: 'response',
                id: 1,
                ok: false,
                error: { code: 'forbidden', message: 'The signed-in user is not allowed to do this.' },
            });
        });

        it('maps HTTP failures to bridge codes', () => {
            const body = (code: string) => ({ code, message: 'x' });
            expect(toBridgeError(new HttpErrorResponse({ status: 400 })).code).toBe('bad_request');
            expect(toBridgeError(new HttpErrorResponse({ status: 404 })).code).toBe('not_found');
            expect(toBridgeError(new HttpErrorResponse({ status: 409, error: body('plugin_suspended') })).code).toBe(
                'forbidden'
            );
            expect(toBridgeError(new HttpErrorResponse({ status: 429 })).code).toBe('rate_limited');
            expect(toBridgeError(new HttpErrorResponse({ status: 500 })).code).toBe('internal');
            expect(toBridgeError(new Error('boom')).code).toBe('internal');
        });
    });

    describe('page-scoped sessions', () => {
        it.each(['sessions.get', 'sessions.subscribe', 'sessions.stop'])(
            'answers %s for a session this page did not start with not_found, before any HTTP',
            (method) => {
                const port = connect();
                startSession(port, 8);

                port.postMessage({ v: 1, kind: 'request', id: 1, method, params: { session_id: 9 } });

                expect(lastError(port)).toMatchObject({ id: 1, ok: false, error: { code: 'not_found' } });
                httpMock.expectNone('/api/sessions/9/');
                httpMock.expectNone('/api/sessions/9/stop/');
                expect(FakeEventSource.instances).toEqual([]);
            }
        );

        it('serves a session this page started with flows.run', () => {
            const port = connect();
            startSession(port, 9);

            port.postMessage({ v: 1, kind: 'request', id: 1, method: 'sessions.get', params: { session_id: 9 } });
            httpMock
                .expectOne('/api/sessions/9/')
                .flush({ id: 9, graph: 42, status: 'end', variables: { answer: 'Hello' } });

            expect(port.received.at(-1)).toEqual({
                v: 1,
                kind: 'response',
                id: 1,
                ok: true,
                result: { status: 'end', variables: { answer: 'Hello' }, flow: 'chat' },
            });
        });

        it('does not carry a session over to the next page attached', () => {
            startSession(connect(), 9);
            const nextPort = connect();

            nextPort.postMessage({ v: 1, kind: 'request', id: 1, method: 'sessions.get', params: { session_id: 9 } });

            expect(lastError(nextPort)).toMatchObject({ id: 1, error: { code: 'not_found' } });
            httpMock.expectNone('/api/sessions/9/');
        });
    });

    describe('caps', () => {
        it('answers a request over 64 KB with bad_request, before any HTTP', () => {
            const port = connect();
            const question = 'x'.repeat(BRIDGE_LIMITS.maxRequestBytes);

            port.postMessage({
                v: 1,
                kind: 'request',
                id: 1,
                method: 'flows.run',
                params: { flow: 'chat', variables: { question } },
            });

            expect(lastError(port).error.code).toBe('bad_request');
            httpMock.expectNone('/api/run-session/');
        });

        it('answers rate_limited past 10 requests in flight', () => {
            const port = connect();

            for (let id = 1; id <= BRIDGE_LIMITS.maxInFlight + 1; id++) {
                port.postMessage({ v: 1, kind: 'request', id, method: 'flows.run', params: { flow: 'chat' } });
            }

            expect(port.received).toEqual([
                expect.objectContaining({
                    id: BRIDGE_LIMITS.maxInFlight + 1,
                    error: expect.objectContaining({ code: 'rate_limited' }),
                }),
            ]);
            expect(httpMock.match(() => true)).toHaveLength(BRIDGE_LIMITS.maxInFlight);
        });

        it('frees an in-flight slot once a request is answered', () => {
            const port = connect();
            for (let id = 1; id <= BRIDGE_LIMITS.maxInFlight; id++) {
                port.postMessage({ v: 1, kind: 'request', id, method: 'flows.run', params: { flow: 'chat' } });
            }
            httpMock.match('/api/run-session/')[0].flush({ session_id: 1 });

            port.postMessage({ v: 1, kind: 'request', id: 99, method: 'bridge.hello' });

            expect(port.received.at(-1)).toMatchObject({ id: 99, ok: true });
            httpMock.match(() => true);
        });

        it('answers rate_limited past 20 runs a minute, and allows runs again a minute later', () => {
            vi.useFakeTimers({ toFake: ['Date'] });
            vi.setSystemTime(new Date('2026-10-07T10:00:00Z'));
            const port = connect();

            for (let id = 1; id <= BRIDGE_LIMITS.maxRunsPerMinute; id++) {
                port.postMessage({ v: 1, kind: 'request', id, method: 'flows.run', params: { flow: 'chat' } });
                httpMock.expectOne('/api/run-session/').flush({ session_id: id });
            }
            port.postMessage({ v: 1, kind: 'request', id: 21, method: 'flows.run', params: { flow: 'chat' } });
            expect(lastError(port)).toMatchObject({ id: 21, error: { code: 'rate_limited' } });
            httpMock.expectNone('/api/run-session/');

            vi.setSystemTime(new Date('2026-10-07T10:01:00.001Z'));
            port.postMessage({ v: 1, kind: 'request', id: 22, method: 'flows.run', params: { flow: 'chat' } });
            httpMock.expectOne('/api/run-session/').flush({ session_id: 22 });
            expect(port.received.at(-1)).toMatchObject({ id: 22, ok: true, result: { session_id: 22 } });
        });

        it('answers rate_limited past 4 open subscriptions, before any HTTP', async () => {
            const port = connect();
            for (let id = 1; id <= BRIDGE_LIMITS.maxSubscriptions + 1; id++) startSession(port, id);
            for (let id = 1; id <= BRIDGE_LIMITS.maxSubscriptions; id++) subscribe(port, id, id);
            await Promise.resolve();

            port.postMessage({ v: 1, kind: 'request', id: 5, method: 'sessions.subscribe', params: { session_id: 5 } });

            expect(lastError(port)).toMatchObject({ id: 5, error: { code: 'rate_limited' } });
            httpMock.expectNone('/api/sessions/5/');
            expect(FakeEventSource.instances).toHaveLength(BRIDGE_LIMITS.maxSubscriptions);
        });
    });

    describe('teardown', () => {
        it("ignores a load before attach (the inserted iframe's about:blank)", () => {
            host.onFrameLoad();
            connect();
            host.onFrameLoad();

            expect(host.stopped()).toBeNull();
            expect(pluginFrame.frame.isConnected).toBe(true);
        });

        it('on a second load closes the port and streams, removes the iframe and reports stopped', async () => {
            const port = connect();
            host.onFrameLoad();
            startSession(port, 9);
            subscribe(port, 1, 9);
            await Promise.resolve();
            const stream = FakeEventSource.instances[0];

            host.onFrameLoad();

            expect(host.stopped()).toBe('navigated');
            expect(host.connected()).toBe(false);
            expect(pluginFrame.frame.isConnected).toBe(false);
            expect(stream.closed).toBe(true);
            expect(port.partner?.closed).toBe(true);
            const received = port.received.length;
            stream.emit('status', { session_id: 9, status: 'end' });
            port.postMessage({ v: 1, kind: 'request', id: 2, method: 'bridge.hello' });
            expect(port.received).toHaveLength(received);
        });

        it('cancels pending HTTP requests on teardown', () => {
            const port = connect();
            startSession(port, 9);
            port.postMessage({ v: 1, kind: 'request', id: 1, method: 'sessions.get', params: { session_id: 9 } });
            const pending = httpMock.expectOne('/api/sessions/9/');

            host.detach();

            expect(pending.cancelled).toBe(true);
        });

        it('stops the page when the active organization changes', () => {
            connect();

            activeOrgId.set(2);
            TestBed.tick();

            expect(host.stopped()).toBe('org_changed');
            expect(pluginFrame.frame.isConnected).toBe(false);
        });

        it('relays a final status, then closes the subscription after the grace period', async () => {
            vi.useFakeTimers();
            const port = connect();
            startSession(port, 9);
            subscribe(port, 1, 9);
            await Promise.resolve();
            const stream = FakeEventSource.instances[0];

            stream.emit('status', { session_id: 9, status: 'end' });
            stream.emit('messages', {
                session_id: 9,
                uuid: 'late',
                name: '',
                message_data: { message_type: 'graph_end' },
            });
            vi.runAllTimers();

            // After the run and subscribe responses.
            expect(port.received.slice(2).map((message) => (message as { topic: string }).topic)).toEqual([
                'session.status',
                'session.message',
                'subscription.closed',
            ]);
            expect(port.received.at(-1)).toMatchObject({ data: { reason: 'ended' } });
            expect(stream.closed).toBe(true);
        });
    });
});
