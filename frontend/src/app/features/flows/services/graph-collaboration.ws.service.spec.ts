import { TestBed } from '@angular/core/testing';
import { of } from 'rxjs';

import { WsTicketService } from '../../../services/auth/ws-ticket.service';
import { ConfigService } from '../../../services/config';
import { GraphCollaborationWsService, GraphSavedMessage, PresentEditor } from './graph-collaboration.ws.service';

/** Stands in for the browser's WebSocket: the test plays the server by calling `receive`. */
class FakeWebSocket {
    static readonly OPEN = 1;
    static last: FakeWebSocket | null = null;

    readyState = FakeWebSocket.OPEN;
    onopen: (() => void) | null = null;
    onmessage: ((event: MessageEvent) => void) | null = null;
    onclose: (() => void) | null = null;
    onerror: ((event: Event) => void) | null = null;

    constructor(readonly url: string) {
        FakeWebSocket.last = this;
    }

    send(): void {}

    close(): void {}

    receive(message: object): void {
        this.onmessage?.({ data: JSON.stringify(message) } as MessageEvent);
    }
}

const ADA: PresentEditor = { user_id: 7, display_name: 'Ada', avatar_url: null };

describe('GraphCollaborationWsService', () => {
    let service: GraphCollaborationWsService;
    let socket: FakeWebSocket;

    beforeEach(() => {
        vi.stubGlobal('WebSocket', FakeWebSocket);
        TestBed.configureTestingModule({
            providers: [
                { provide: ConfigService, useValue: { apiUrl: 'http://localhost/api/' } },
                { provide: WsTicketService, useValue: { fetchTicket: () => of('ticket') } },
            ],
        });
        service = TestBed.inject(GraphCollaborationWsService);
        service.connect(1);
        socket = FakeWebSocket.last!;
        socket.onopen?.();
        socket.receive({ type: 'presence_state', editors: [ADA] });
    });

    afterEach(() => {
        service.disconnect();
        FakeWebSocket.last = null;
        vi.unstubAllGlobals();
    });

    it('passes on a save by a plugin, which has no user id, with its name', () => {
        const saves: GraphSavedMessage[] = [];
        service.graphSaved$.subscribe((message) => saves.push(message));

        socket.receive({
            type: 'graph_saved',
            graph_id: 1,
            new_save_version: 4,
            saved_by: { user_id: null, display_name: 'Weather (plugin)', avatar_url: null },
            saved_at: '2026-10-21T08:00:00Z',
        });

        expect(saves).toHaveLength(1);
        expect(saves[0].saved_by).toEqual({ user_id: null, display_name: 'Weather (plugin)', avatar_url: null });
        expect(service.editors()).toEqual([ADA]);
    });

    it("refreshes a present person's details when they save", () => {
        socket.receive({
            type: 'graph_saved',
            graph_id: 1,
            new_save_version: 5,
            saved_by: { user_id: 7, display_name: 'Ada Lovelace', avatar_url: '/media/ada.png' },
            saved_at: '2026-10-21T08:00:00Z',
        });

        expect(service.editors()).toEqual([{ user_id: 7, display_name: 'Ada Lovelace', avatar_url: '/media/ada.png' }]);
    });
});
