import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';

import { ConfigService } from '../../../services/config';
import { ChatConversation, ChatInboxMessageEvent } from '../models/chat.model';
import { ChatInboxStreamService } from './chat-inbox-stream.service';

/** Minimal EventSource double: records instances, lets a test fire named events. */
class FakeEventSource {
    static instances: FakeEventSource[] = [];
    readonly listeners = new Map<string, ((event: MessageEvent) => void)[]>();
    onopen: (() => void) | null = null;
    onerror: (() => void) | null = null;
    closed = false;

    constructor(readonly url: string) {
        FakeEventSource.instances.push(this);
    }

    addEventListener(type: string, listener: (event: MessageEvent) => void): void {
        this.listeners.set(type, [...(this.listeners.get(type) ?? []), listener]);
    }

    close(): void {
        this.closed = true;
    }

    emit(type: string, data: unknown, lastEventId = ''): void {
        const event = new MessageEvent(type, { data: JSON.stringify(data), lastEventId });
        for (const listener of this.listeners.get(type) ?? []) listener(event);
    }
}

const conversation = (overrides: Partial<ChatConversation>): ChatConversation => ({
    id: 'c-1',
    binding_id: 'b-1',
    mode: 'bot',
    state: 'idle',
    is_test: false,
    assigned_operator_id: null,
    tokens_used: 0,
    turns: 0,
    tokens_today: 0,
    turns_today: 0,
    last_message_at: null,
    last_message_preview: '',
    handoff_reason: '',
    handoff_at: null,
    ...overrides,
});

describe('ChatInboxStreamService', () => {
    let service: ChatInboxStreamService;
    let httpMock: HttpTestingController;

    const ticketUrl = '/chat/operator/v1/inbox/stream-ticket';
    const seedUrl =
        (cursor: string | null = null) =>
        (request: { url: string; params: { get(name: string): string | null } }): boolean =>
            request.url === '/chat/operator/v1/conversations' &&
            request.params.get('section') === 'human' &&
            request.params.get('mode') === 'awaiting_human' &&
            request.params.get('cursor') === cursor;
    const awaitingPage = (ids: string[], nextCursor: string | null = null) => ({
        results: ids.map((id) => conversation({ id, mode: 'awaiting_human' })),
        next_cursor: nextCursor,
    });

    function openStream(ticket = 't-1'): FakeEventSource {
        httpMock.expectOne(ticketUrl).flush({ ticket, expires_in: 60 });
        const source = FakeEventSource.instances.at(-1)!;
        source.onopen?.();
        return source;
    }

    beforeEach(() => {
        FakeEventSource.instances = [];
        vi.stubGlobal('EventSource', FakeEventSource);
        TestBed.configureTestingModule({
            providers: [
                provideHttpClient(),
                provideHttpClientTesting(),
                { provide: ConfigService, useValue: { chatApiUrl: '/chat/' } as unknown as ConfigService },
            ],
        });
        service = TestBed.inject(ChatInboxStreamService);
        httpMock = TestBed.inject(HttpTestingController);
    });

    afterEach(() => {
        service.stop();
        httpMock.verify();
        vi.unstubAllGlobals();
        vi.useRealTimers();
    });

    it('mints a ticket, opens the stream, bumps the ready epoch and seeds the awaiting badge on ready', () => {
        service.start(1);
        const source = openStream();
        expect(source.url).toBe('/chat/operator/v1/inbox/stream?ticket=t-1');
        expect(service.status()).toBe('open');
        expect(service.readyEpoch()).toBe(0);

        source.emit('ready', {}, '42');
        expect(service.readyEpoch()).toBe(1);
        httpMock.expectOne(seedUrl()).flush(awaitingPage(['c-1', 'c-2', 'c-3']));
        expect(service.awaitingCount()).toBe(3);
    });

    it('seeds the awaiting badge across cursor pages until next_cursor is null', () => {
        service.start(1);
        const source = openStream();
        source.emit('ready', {}, '1');
        httpMock.expectOne(seedUrl()).flush(awaitingPage(['c-1', 'c-2'], 'cursor-2'));
        expect(service.awaitingCount()).toBe(0);
        httpMock.expectOne(seedUrl('cursor-2')).flush(awaitingPage(['c-3']));
        expect(service.awaitingCount()).toBe(3);
    });

    it('adds and removes awaiting ids from conversation updates', () => {
        service.start(1);
        const source = openStream();
        source.emit('ready', {}, '1');
        httpMock.expectOne(seedUrl()).flush(awaitingPage(['c-1']));

        source.emit('conversation.updated', conversation({ id: 'c-2', mode: 'awaiting_human' }), '5');
        expect(service.awaitingCount()).toBe(2);
        source.emit('conversation.updated', conversation({ id: 'c-1', mode: 'human' }), '6');
        source.emit('conversation.updated', conversation({ id: 'c-2', mode: 'awaiting_human' }), '7');
        expect(service.awaitingCount()).toBe(1);
        // An older snapshot is deduped before it can touch the badge.
        source.emit('conversation.updated', conversation({ id: 'c-1', mode: 'awaiting_human' }), '4');
        expect(service.awaitingCount()).toBe(1);
    });

    it('counts awaiting conversations per binding from the seed and from updates', () => {
        service.start(1);
        const source = openStream();
        source.emit('ready', {}, '1');
        httpMock.expectOne(seedUrl()).flush({
            results: [
                conversation({ id: 'c-1', binding_id: 'b-1', mode: 'awaiting_human' }),
                conversation({ id: 'c-2', binding_id: 'b-2', mode: 'awaiting_human' }),
            ],
            next_cursor: null,
        });
        expect(service.awaitingByBinding()).toEqual({ 'b-1': 1, 'b-2': 1 });

        source.emit(
            'conversation.updated',
            conversation({ id: 'c-3', binding_id: 'b-1', mode: 'awaiting_human' }),
            '5'
        );
        source.emit('conversation.updated', conversation({ id: 'c-2', binding_id: 'b-2', mode: 'human' }), '6');
        expect(service.awaitingByBinding()).toEqual({ 'b-1': 2 });
        expect(service.awaitingCount()).toBe(2);

        service.stop();
        expect(service.awaitingByBinding()).toEqual({});
    });

    it('never counts a test conversation as waiting', () => {
        service.start(1);
        const source = openStream();
        source.emit('ready', {}, '1');
        httpMock.expectOne(seedUrl()).flush(awaitingPage([]));
        source.emit('conversation.updated', conversation({ id: 'c-9', mode: 'awaiting_human', is_test: true }), '5');
        expect(service.awaitingCount()).toBe(0);
        expect(service.awaitingByBinding()).toEqual({});
    });

    it('replays updates that arrive while the seed is in flight over the seed', () => {
        service.start(1);
        const source = openStream();
        source.emit('ready', {}, '1');
        const firstPage = httpMock.expectOne(seedUrl());

        source.emit('conversation.updated', conversation({ id: 'c-1', mode: 'human' }), '5');
        source.emit('conversation.updated', conversation({ id: 'c-8', mode: 'awaiting_human' }), '6');
        source.emit('conversation.updated', conversation({ id: 'c-9', mode: 'awaiting_human' }), '7');
        firstPage.flush(awaitingPage(['c-1', 'c-2'], 'cursor-2'));
        httpMock.expectOne(seedUrl('cursor-2')).flush(awaitingPage(['c-3']));

        // c-1 left awaiting after the snapshot listed it; c-8 and c-9 entered without being on any page.
        // Without the replay the badge would read 3 (pages only); a plain union would read 5.
        expect(service.awaitingCount()).toBe(4);
    });

    it('ends the seed when the server repeats the cursor it was given', () => {
        service.start(1);
        const source = openStream();
        source.emit('ready', {}, '1');
        httpMock.expectOne(seedUrl()).flush(awaitingPage(['c-1'], 'cursor-2'));
        httpMock.expectOne(seedUrl('cursor-2')).flush(awaitingPage(['c-2'], 'cursor-2'));

        httpMock.expectNone(seedUrl('cursor-2'));
        expect(service.awaitingCount()).toBe(2);
    });

    it('ignores a seed from an earlier ready once a newer one starts', () => {
        service.start(1);
        const source = openStream();
        source.emit('ready', {}, '1');
        const stale = httpMock.expectOne(seedUrl());
        source.emit('ready', {}, '2');

        expect(stale.cancelled).toBe(true);
        httpMock.expectOne(seedUrl()).flush(awaitingPage(['c-1']));
        expect(service.awaitingCount()).toBe(1);
    });

    it('ignores a seed from a previous org', () => {
        service.start(1);
        openStream('t-1').emit('ready', {}, '1');
        const stale = httpMock.expectOne(seedUrl());
        service.start(2);

        expect(stale.cancelled).toBe(true);
        openStream('t-2').emit('ready', {}, '1');
        httpMock.expectOne(seedUrl()).flush(awaitingPage([]));
        expect(service.awaitingCount()).toBe(0);
    });

    it('is idempotent for the same org and restarts for another org', () => {
        service.start(1);
        const first = openStream('t-1');
        service.start(1);
        expect(FakeEventSource.instances).toHaveLength(1);

        service.start(2);
        expect(first.closed).toBe(true);
        openStream('t-2');
        expect(FakeEventSource.instances).toHaveLength(2);
    });

    it('drops a conversation snapshot older than one already seen for that conversation', () => {
        const seen: ChatConversation[] = [];
        service.conversationUpdated$.subscribe((row) => seen.push(row));
        service.start(1);
        const source = openStream();

        source.emit('conversation.updated', conversation({ id: 'c-1', mode: 'human' }), '10');
        source.emit('conversation.updated', conversation({ id: 'c-1', mode: 'bot' }), '9');
        source.emit('conversation.updated', conversation({ id: 'c-2', mode: 'bot' }), '8');

        expect(seen.map((row) => `${row.id}:${row.mode}`)).toEqual(['c-1:human', 'c-2:bot']);
    });

    it('forwards a conversation snapshot that carries no usable event id', () => {
        const seen: ChatConversation[] = [];
        service.conversationUpdated$.subscribe((row) => seen.push(row));
        service.start(1);
        const source = openStream();

        source.emit('conversation.updated', conversation({ id: 'c-1', mode: 'human' }), '');

        expect(seen.map((row) => row.mode)).toEqual(['human']);
    });

    it('keeps the previous awaiting count when the seed fails', () => {
        service.start(1);
        const source = openStream();
        source.emit('ready', {}, '1');
        httpMock.expectOne(seedUrl()).flush(awaitingPage(['c-1', 'c-2', 'c-3']));

        source.emit('ready', {}, '2');
        httpMock.expectOne(seedUrl()).flush('boom', { status: 500, statusText: 'Server Error' });

        expect(service.awaitingCount()).toBe(3);
    });

    it('forwards message.created events', () => {
        const seen: ChatInboxMessageEvent[] = [];
        service.messageCreated$.subscribe((event) => seen.push(event));
        service.start(1);
        const source = openStream();
        const event: ChatInboxMessageEvent = {
            conversation_id: 'c-1',
            id: 'm-1',
            role: 'user',
            content: 'hi',
            actions: null,
            action: null,
            created_at: '2026-10-10T10:00:00Z',
        };
        source.emit('message.created', event, '11');
        expect(seen).toEqual([event]);
    });

    it('reconnects with a fresh ticket after a backoff when the stream errors', () => {
        vi.useFakeTimers();
        service.start(1);
        const source = openStream('t-1');
        source.onerror?.();
        expect(source.closed).toBe(true);
        expect(service.status()).toBe('reconnecting');
        httpMock.expectNone(ticketUrl);

        vi.advanceTimersByTime(1100);
        openStream('t-2');
        expect(FakeEventSource.instances.at(-1)!.url).toContain('t-2');
        expect(service.status()).toBe('open');
    });

    it('stop closes the stream and resets the count', () => {
        service.start(1);
        const source = openStream();
        service.stop();
        expect(source.closed).toBe(true);
        expect(service.status()).toBe('closed');
        expect(service.awaitingCount()).toBe(0);
    });
});
