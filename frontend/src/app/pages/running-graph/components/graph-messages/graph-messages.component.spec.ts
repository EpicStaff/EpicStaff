import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { Component } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { GraphSessionStatus } from '@shared/models';
import { firstValueFrom, of } from 'rxjs';

import { SseTicketService } from '../../../../services/auth/sse-ticket.service';
import { ConfigService } from '../../../../services/config';
import { ToastService } from '../../../../services/notifications';
import { GraphMessage, MessageData, MessageType } from '../../models/graph-session-message.model';
import { GraphMessagesComponent } from './graph-messages.component';

const GRAPH_ID = 3;
const BILLING_FLOW_ID = 8;
const ARCHIVE_FLOW_ID = 9;
const DELETED_FLOW_ID = 77;
const SESSION_ID = '5';
const OTHER_SESSION_ID = '6';

const VISIBLE_FLOWS = [
    { id: GRAPH_ID, name: 'Orders' },
    { id: BILLING_FLOW_ID, name: 'Billing' },
    { id: ARCHIVE_FLOW_ID, name: 'Archive' },
];

let nextMessageId = 1;

/**
 * `runChain` is the subflow runs the message was sent from inside, innermost first. Crew adds it as
 * `subgraph_execution_ids` on the way out of each run, so a top-level message has none.
 */
function message(name: string, data: MessageData, runChain: string[] = []): GraphMessage {
    const id = nextMessageId++;
    return {
        id,
        session: Number(SESSION_ID),
        name,
        execution_order: id,
        created_at: `2026-10-21T10:00:${String(id).padStart(2, '0')}Z`,
        uuid: `message-${id}`,
        metadata: {},
        message_data: runChain.length ? Object.assign({ subgraph_execution_ids: runChain }, data) : data,
    };
}

function startMessage(name: string, runChain: string[] = []): GraphMessage {
    return message(name, { message_type: MessageType.START, input: {} }, runChain);
}

function finishMessage(name: string, runChain: string[] = []): GraphMessage {
    return message(name, { message_type: MessageType.FINISH, output: {}, state: {} }, runChain);
}

function agentStreamMessage(name: string): GraphMessage {
    return message(name, {
        message_type: MessageType.AGENT_NODE_STREAM,
        event: 'task_start',
        step_id: 1,
        is_final: false,
        data: { task: { name: 'Research', order: 1 } },
    });
}

function errorMessage(name: string, runChain: string[] = []): GraphMessage {
    return message(name, { message_type: MessageType.ERROR, details: `${name} failed` }, runChain);
}

function conditionGroupMessage(name: string, runChain: string[] = []): GraphMessage {
    return message(
        name,
        { message_type: MessageType.CONDITION_GROUP, group_name: 'Group 1', result: true, expression: null },
        runChain
    );
}

/** `runId` is the run this start opens; `runChain` the runs the start itself was sent from inside. */
function subgraphStartMessage(
    name: string,
    subgraphId: number,
    runId = 'run-1',
    runChain: string[] = []
): GraphMessage {
    return message(
        name,
        {
            message_type: MessageType.SUBGRAPH_START,
            input: {},
            state: { variables: {}, state_history: [] },
            subgraph_id: subgraphId,
            subgraph_execution_id: runId,
            messages_count_by_subgraph: {},
        },
        runChain
    );
}

function rootGraph(subgraphNodes: { id: number; node_name: string; subgraph: number }[] = []) {
    return { id: GRAPH_ID, name: 'Orders', subgraph_node_list: subgraphNodes };
}

function page<T>(results: T[], next: string | null = null) {
    return { count: results.length, next, previous: null, results };
}

interface SessionPayload {
    status: GraphSessionStatus;
    status_data?: Record<string, unknown>;
}

const TOKEN_BUDGET_REASON = 'The flow stopped: it used up its token budget.';

/** Minimal EventSource double: records instances, lets a test fire named events. */
class FakeEventSource {
    static instances: FakeEventSource[] = [];
    readonly listeners = new Map<string, ((event: MessageEvent) => void)[]>();
    onopen: (() => void) | null = null;
    onerror: (() => void) | null = null;
    onmessage: (() => void) | null = null;

    constructor(readonly url: string) {
        FakeEventSource.instances.push(this);
    }

    addEventListener(type: string, listener: (event: MessageEvent) => void): void {
        this.listeners.set(type, [...(this.listeners.get(type) ?? []), listener]);
    }

    close(): void {}

    emit(type: string, data: unknown): void {
        const event = new MessageEvent(type, { data: JSON.stringify(data) });
        for (const listener of this.listeners.get(type) ?? []) listener(event);
    }
}

@Component({ template: '' })
class SessionsPageStub {}

/**
 * Plays the backend for one ended session. Every endpoint must be called exactly as often as
 * stated here: `expectOne` fails on a missing or repeated call, and `verify()` in afterEach fails
 * on any request nobody answered.
 */
function serveFinishedSession(
    fixture: ComponentFixture<GraphMessagesComponent>,
    httpMock: HttpTestingController,
    sessionMessages: GraphMessage[],
    graph = rootGraph(),
    session: SessionPayload = { status: GraphSessionStatus.ENDED },
    sessionId = SESSION_ID
): void {
    httpMock
        .expectOne((request) => request.url === `/api/sessions/${sessionId}/`)
        .flush({ id: Number(sessionId), status_data: {}, ...session });
    serveFlows(httpMock, graph, sessionId);
    fixture.detectChanges();

    // A finished session reads its messages twice: the first page, and one reconcile pass that
    // backfills anything the live stream missed.
    const messageReads = httpMock.match((request) => request.url === '/api/graph-session-messages/');
    expect(messageReads).toHaveLength(2);
    messageReads.forEach((read) => read.flush(page(sessionMessages)));
    fixture.detectChanges();
}

function serveFlows(httpMock: HttpTestingController, graph = rootGraph(), sessionId = SESSION_ID): void {
    httpMock.expectOne((request) => request.url === `/api/sessions/${sessionId}/warnings/`).flush({ messages: [] });
    httpMock.expectOne((request) => request.url === `/api/graphs/${GRAPH_ID}/`).flush(graph);
    httpMock.expectOne((request) => request.url === '/api/graph-light/').flush(page(VISIBLE_FLOWS));
}

function texts(element: HTMLElement, selector: string): string[] {
    return Array.from(element.querySelectorAll(selector)).map((node) => node.textContent?.trim() ?? '');
}

describe('GraphMessagesComponent', () => {
    let httpMock: HttpTestingController;

    function create(): ComponentFixture<GraphMessagesComponent> {
        const fixture = TestBed.createComponent(GraphMessagesComponent);
        fixture.componentRef.setInput('graphId', GRAPH_ID);
        fixture.componentRef.setInput('sessionId', SESSION_ID);
        fixture.detectChanges();
        return fixture;
    }

    function render(
        sessionMessages: GraphMessage[],
        graph = rootGraph(),
        session: SessionPayload = { status: GraphSessionStatus.ENDED }
    ): HTMLElement {
        const fixture = create();
        serveFinishedSession(fixture, httpMock, sessionMessages, graph, session);
        return fixture.nativeElement as HTMLElement;
    }

    /** Opens a running session's live stream; the returned fake plays the server's side of it. */
    function renderRunningSession(): { fixture: ComponentFixture<GraphMessagesComponent>; stream: FakeEventSource } {
        const fixture = create();
        httpMock
            .expectOne((request) => request.url === `/api/sessions/${SESSION_ID}/`)
            .flush({ id: Number(SESSION_ID), status: GraphSessionStatus.RUNNING, status_data: {} });
        serveFlows(httpMock);
        httpMock.expectOne((request) => request.url === '/api/graph-session-messages/').flush(page([]));
        fixture.detectChanges();
        return { fixture, stream: FakeEventSource.instances[0] };
    }

    /** The stream reports the session's end; the panel then reads the stored messages once more. */
    function endSession(
        fixture: ComponentFixture<GraphMessagesComponent>,
        stream: FakeEventSource,
        statusEvent: Record<string, unknown>
    ): void {
        stream.emit('status', statusEvent);
        fixture.detectChanges();
        httpMock.expectOne((request) => request.url === '/api/graph-session-messages/').flush(page([]));
        fixture.detectChanges();
    }

    beforeEach(() => {
        FakeEventSource.instances = [];
        vi.stubGlobal('EventSource', FakeEventSource);
        TestBed.configureTestingModule({
            imports: [GraphMessagesComponent],
            providers: [
                provideRouter([{ path: 'sessions', component: SessionsPageStub }]),
                provideHttpClient(),
                provideHttpClientTesting(),
                { provide: ConfigService, useValue: { apiUrl: '/api/' } as unknown as ConfigService },
                { provide: SseTicketService, useValue: { fetchTicket: () => of('ticket') } },
            ],
        });
        httpMock = TestBed.inject(HttpTestingController);
    });

    afterEach(() => {
        httpMock.verify();
        vi.unstubAllGlobals();
    });

    it('shows a node by its label, without the node id the backend appends to its name', () => {
        const element = render([startMessage('Fetch #3 #1742'), finishMessage('Fetch #3 #1742')]);

        expect(texts(element, 'app-start-message .node-name')).toEqual(['Fetch #3']);
        expect(texts(element, 'app-finish-message .node-name')).toEqual(['Fetch #3']);
    });

    it('keeps the stream cards of two nodes with the same label apart', () => {
        const element = render([agentStreamMessage('A #1 #10'), agentStreamMessage('A #1 #11')]);

        expect(texts(element, 'app-node-stream-message .node-name')).toEqual(['A #1', 'A #1']);
    });

    it('names the flow the subgraph start message says ran, without loading that flow', () => {
        const graph = rootGraph([
            { id: 54, node_name: 'Sub', subgraph: ARCHIVE_FLOW_ID },
            { id: 55, node_name: 'Sub', subgraph: BILLING_FLOW_ID },
        ]);

        const element = render([subgraphStartMessage('Sub #2 #55', BILLING_FLOW_ID)], graph);

        expect(texts(element, 'app-subgraph-start-message .node-name')).toEqual(['Sub #2']);
        expect(texts(element, 'app-subgraph-start-message h3')[0]).toContain('subgraph started Billing');
        httpMock.expectNone((request) => request.url.startsWith(`/api/graphs/${BILLING_FLOW_ID}`));
    });

    it('leaves the subgraph unnamed when the flow that ran is not among the visible flows', () => {
        const element = render([subgraphStartMessage('Sub #2 #55', DELETED_FLOW_ID)]);

        const header = texts(element, 'app-subgraph-start-message h3')[0];
        expect(header).toMatch(/subgraph started$/);
    });

    describe('the reason a session ended early', () => {
        it.each([
            {
                status: GraphSessionStatus.ERROR,
                statusData: { error: TOKEN_BUDGET_REASON },
                shown: [TOKEN_BUDGET_REASON],
            },
            {
                status: GraphSessionStatus.STOP,
                statusData: { error: TOKEN_BUDGET_REASON },
                shown: [TOKEN_BUDGET_REASON],
            },
            {
                status: GraphSessionStatus.EXPIRED,
                statusData: { error: TOKEN_BUDGET_REASON },
                shown: [TOKEN_BUDGET_REASON],
            },
            { status: GraphSessionStatus.STOP, statusData: {}, shown: [] },
            { status: GraphSessionStatus.ERROR, statusData: { error: '   ' }, shown: [] },
            { status: GraphSessionStatus.ENDED, statusData: { error: TOKEN_BUDGET_REASON }, shown: [] },
        ])('for a stored $status session with $statusData shows $shown', ({ status, statusData, shown }) => {
            const element = render([startMessage('Fetch #1 #3')], rootGraph(), { status, status_data: statusData });

            expect(texts(element, '.session-end-reason__text')).toEqual(shown);
        });

        it('shows the reason the live stream reports when the session fails', () => {
            const { fixture, stream } = renderRunningSession();

            endSession(fixture, stream, {
                session_id: SESSION_ID,
                status: GraphSessionStatus.ERROR,
                status_data: { error: TOKEN_BUDGET_REASON },
            });

            expect(texts(fixture.nativeElement, '.session-end-reason__text')).toEqual([TOKEN_BUDGET_REASON]);
        });

        it('keeps the reason when a later status event carries no status data', () => {
            const { fixture, stream } = renderRunningSession();
            endSession(fixture, stream, {
                session_id: SESSION_ID,
                status: GraphSessionStatus.ERROR,
                status_data: { error: TOKEN_BUDGET_REASON },
            });

            stream.emit('status', { session_id: SESSION_ID, status: GraphSessionStatus.ERROR });
            fixture.detectChanges();

            expect(texts(fixture.nativeElement, '.session-end-reason__text')).toEqual([TOKEN_BUDGET_REASON]);
        });

        it("drops the previous session's reason when switching to a session that gives none", () => {
            const fixture = create();
            serveFinishedSession(fixture, httpMock, [startMessage('Fetch #1 #3')], rootGraph(), {
                status: GraphSessionStatus.ERROR,
                status_data: { error: TOKEN_BUDGET_REASON },
            });
            expect(texts(fixture.nativeElement, '.session-end-reason__text')).toEqual([TOKEN_BUDGET_REASON]);

            fixture.componentRef.setInput('sessionId', OTHER_SESSION_ID);
            fixture.detectChanges();
            serveFinishedSession(
                fixture,
                httpMock,
                [],
                rootGraph(),
                { status: GraphSessionStatus.STOP },
                OTHER_SESSION_ID
            );

            expect(fixture.nativeElement.querySelector('.session-end-reason')).toBeNull();
        });

        it('waits for the last page of messages before showing the reason', () => {
            const fixture = create();
            httpMock
                .expectOne((request) => request.url === `/api/sessions/${SESSION_ID}/`)
                .flush({
                    id: Number(SESSION_ID),
                    status: GraphSessionStatus.ERROR,
                    status_data: { error: TOKEN_BUDGET_REASON },
                });
            serveFlows(httpMock);
            fixture.detectChanges();
            // The first page and the reconcile pass both report another page; the reconcile pass reads it at once.
            httpMock
                .match((request) => request.url === '/api/graph-session-messages/')
                .forEach((read) => read.flush(page([startMessage('Fetch #1 #3')], 'next-page')));
            httpMock.expectOne((request) => request.url === '/api/graph-session-messages/').flush(page([]));
            fixture.detectChanges();

            expect(fixture.nativeElement.querySelector('.session-end-reason')).toBeNull();

            fixture.componentInstance.loadMoreMessages();
            httpMock.expectOne((request) => request.url === '/api/graph-session-messages/').flush(page([]));
            fixture.detectChanges();

            expect(texts(fixture.nativeElement, '.session-end-reason__text')).toEqual([TOKEN_BUDGET_REASON]);
        });

        it('shows nothing for a stop whose status event carries no status data', () => {
            const { fixture, stream } = renderRunningSession();

            endSession(fixture, stream, { session_id: SESSION_ID, status: GraphSessionStatus.STOP });

            expect(fixture.nativeElement.querySelector('.session-end-reason')).toBeNull();
        });
    });

    describe('a group whose node failed instead of finishing', () => {
        it.each([
            {
                case: "a subflow node's own error closes its group",
                messages: () => [
                    subgraphStartMessage('Sub #1 #5', BILLING_FLOW_ID, 'run-1'),
                    startMessage('Py #1 #6', ['run-1']),
                    finishMessage('Py #1 #6', ['run-1']),
                    errorMessage('Sub #1 #5'),
                ],
                topLevelErrors: ['Sub #1'],
            },
            {
                case: "an inner subflow node's error stays in the outer group, the outer one's shows on top",
                messages: () => [
                    subgraphStartMessage('Outer #1 #5', BILLING_FLOW_ID, 'run-1'),
                    subgraphStartMessage('Inner #1 #7', ARCHIVE_FLOW_ID, 'run-2', ['run-1']),
                    errorMessage('Inner #1 #7', ['run-1']),
                    errorMessage('Outer #1 #5'),
                ],
                topLevelErrors: ['Outer #1'],
            },
            {
                case: "a decision table node's own error closes its group",
                messages: () => [
                    startMessage('Table #1 #9'),
                    conditionGroupMessage('Table #1 #9'),
                    errorMessage('Table #1 #9'),
                ],
                topLevelErrors: ['Table #1'],
            },
        ])('$case', ({ messages, topLevelErrors }) => {
            const element = render(messages());

            expect(texts(element, '.messages-list > .message > app-error-message .node-name')).toEqual(topLevelErrors);
        });

        it.each([
            {
                case: 'an error of a node inside the subflow',
                messages: () => [
                    subgraphStartMessage('Sub #1 #5', BILLING_FLOW_ID, 'run-1'),
                    startMessage('Py #1 #6', ['run-1']),
                    errorMessage('Py #1 #6', ['run-1']),
                ],
                nestedErrors: ['Py #1'],
            },
            {
                case: "in a flow that runs itself, the inner subflow node's error after its start",
                messages: () => [
                    subgraphStartMessage('Sub #1 #5', GRAPH_ID, 'run-1'),
                    subgraphStartMessage('Sub #1 #5', GRAPH_ID, 'run-2', ['run-1']),
                    errorMessage('Sub #1 #5', ['run-1']),
                ],
                nestedErrors: ['Sub #1'],
            },
            {
                case: "in a flow that runs itself, the inner subflow node's error before its start",
                messages: () => [
                    subgraphStartMessage('Sub #1 #5', GRAPH_ID, 'run-1'),
                    errorMessage('Sub #1 #5', ['run-1']),
                ],
                nestedErrors: ['Sub #1'],
            },
        ])('keeps $case inside the group it ran in', ({ messages, nestedErrors }) => {
            const fixture = create();
            serveFinishedSession(fixture, httpMock, messages());
            const element = fixture.nativeElement as HTMLElement;
            expect(texts(element, '.messages-list > .message > app-error-message .node-name')).toEqual([]);

            element.querySelector<HTMLButtonElement>('app-subgraph-start-message .view-nested-button')!.click();
            fixture.detectChanges();
            // A finished session reads the group's messages when it is opened; they are already shown.
            httpMock.expectOne((request) => request.url === '/api/graph-session-messages/').flush(page([]));
            fixture.detectChanges();

            expect(texts(element, '.subgraph-drilldown__messages app-error-message .node-name')).toEqual(nestedErrors);
        });
    });

    describe('when the session cannot be loaded', () => {
        it.each([
            {
                case: "the server's message",
                response: { status: 404, statusText: 'Not Found', body: { message: 'Session not found.' } },
                toast: "Couldn't load the session. Session not found.",
            },
            {
                case: 'a plain sentence when the server is unreachable',
                response: { status: 0, statusText: 'Unknown Error', body: null },
                toast: "Couldn't load the session. The server couldn't be reached. Check your connection and try again.",
            },
        ])('shows $case after the heading', async ({ response, toast }) => {
            const fixture = create();

            httpMock
                .expectOne((request) => request.url === `/api/sessions/${SESSION_ID}/`)
                .flush(response.body, { status: response.status, statusText: response.statusText });
            serveFlows(httpMock);
            fixture.detectChanges();

            const [shown] = await firstValueFrom(TestBed.inject(ToastService).toasts$);
            expect(shown).toMatchObject({ message: toast, type: 'error' });
        });
    });
});
