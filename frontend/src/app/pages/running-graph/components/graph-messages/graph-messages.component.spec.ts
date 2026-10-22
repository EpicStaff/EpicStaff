import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { GraphSessionStatus } from '@shared/models';

import { ConfigService } from '../../../../services/config';
import { GraphMessage, MessageData, MessageType } from '../../models/graph-session-message.model';
import { GraphMessagesComponent } from './graph-messages.component';

const GRAPH_ID = 3;
const BILLING_FLOW_ID = 8;
const ARCHIVE_FLOW_ID = 9;
const DELETED_FLOW_ID = 77;
const SESSION_ID = '5';

const VISIBLE_FLOWS = [
    { id: GRAPH_ID, name: 'Orders' },
    { id: BILLING_FLOW_ID, name: 'Billing' },
    { id: ARCHIVE_FLOW_ID, name: 'Archive' },
];

let nextMessageId = 1;

function message(name: string, data: MessageData): GraphMessage {
    const id = nextMessageId++;
    return {
        id,
        session: Number(SESSION_ID),
        name,
        execution_order: id,
        created_at: `2026-10-21T10:00:${String(id).padStart(2, '0')}Z`,
        uuid: `message-${id}`,
        metadata: {},
        message_data: data,
    };
}

function startMessage(name: string): GraphMessage {
    return message(name, { message_type: MessageType.START, input: {} });
}

function finishMessage(name: string): GraphMessage {
    return message(name, { message_type: MessageType.FINISH, output: {}, state: {} });
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

function subgraphStartMessage(name: string, subgraphId: number): GraphMessage {
    return message(name, {
        message_type: MessageType.SUBGRAPH_START,
        input: {},
        state: { variables: {}, state_history: [] },
        subgraph_id: subgraphId,
        messages_count_by_subgraph: {},
    });
}

function rootGraph(subgraphNodes: { id: number; node_name: string; subgraph: number }[] = []) {
    return { id: GRAPH_ID, name: 'Orders', subgraph_node_list: subgraphNodes };
}

function page<T>(results: T[]) {
    return { count: results.length, next: null, previous: null, results };
}

/**
 * Plays the backend for one ended session. Every endpoint must be called exactly as often as
 * stated here: `expectOne` fails on a missing or repeated call, and `verify()` in afterEach fails
 * on any request nobody answered.
 */
function serveEndedSession(
    fixture: ComponentFixture<GraphMessagesComponent>,
    httpMock: HttpTestingController,
    sessionMessages: GraphMessage[],
    graph = rootGraph()
): void {
    httpMock
        .expectOne((request) => request.url === `/api/sessions/${SESSION_ID}/`)
        .flush({ id: Number(SESSION_ID), status: GraphSessionStatus.ENDED });
    httpMock.expectOne((request) => request.url === `/api/sessions/${SESSION_ID}/warnings/`).flush({ messages: [] });
    httpMock.expectOne((request) => request.url === `/api/graphs/${GRAPH_ID}/`).flush(graph);
    httpMock.expectOne((request) => request.url === '/api/graph-light/').flush(page(VISIBLE_FLOWS));
    fixture.detectChanges();

    // An ended session reads its messages twice: the first page, and one reconcile pass that
    // backfills anything the live stream missed.
    const messageReads = httpMock.match((request) => request.url === '/api/graph-session-messages/');
    expect(messageReads).toHaveLength(2);
    messageReads.forEach((read) => read.flush(page(sessionMessages)));
    fixture.detectChanges();
}

function texts(element: HTMLElement, selector: string): string[] {
    return Array.from(element.querySelectorAll(selector)).map((node) => node.textContent?.trim() ?? '');
}

describe('GraphMessagesComponent', () => {
    let httpMock: HttpTestingController;

    function render(sessionMessages: GraphMessage[], graph = rootGraph()): HTMLElement {
        const fixture = TestBed.createComponent(GraphMessagesComponent);
        fixture.componentRef.setInput('graphId', GRAPH_ID);
        fixture.componentRef.setInput('sessionId', SESSION_ID);
        fixture.detectChanges();
        serveEndedSession(fixture, httpMock, sessionMessages, graph);
        return fixture.nativeElement as HTMLElement;
    }

    beforeEach(() => {
        TestBed.configureTestingModule({
            imports: [GraphMessagesComponent],
            providers: [
                provideRouter([]),
                provideHttpClient(),
                provideHttpClientTesting(),
                { provide: ConfigService, useValue: { apiUrl: '/api/' } as unknown as ConfigService },
            ],
        });
        httpMock = TestBed.inject(HttpTestingController);
    });

    afterEach(() => httpMock.verify());

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
});
