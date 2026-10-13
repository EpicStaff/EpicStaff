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
    visitor_number: 1,
    chat_user_id: null,
    assigned_operator_name: null,
    last_message_role: 'user',
    last_message_author_user_id: null,
    last_message_author_name: null,
    visitor_waiting_since: null,
    ...overrides,
});

describe('ChatInboxStreamService', () => {
    let service: ChatInboxStreamService;
    let httpMock: HttpTestingController;

    const ticketUrl = '/chat/operator/v1/inbox/stream-ticket';
    const badgesUrl = '/chat/operator/v1/inbox/badges';
    const at = '2026-10-10T10:00:00Z';
    const badge = (id: string, bindingId = 'b-1', holderId: number | null = null) => ({
        id,
        binding_id: bindingId,
        assigned_operator_id: holderId,
    });
    const badges = (ids: string[]) => ({ waiting: ids.map((id) => badge(id)) });
    /** The after-state of a conversation a visitor waits on (taken by `holderId` when set). */
    const waiting = (id: string, overrides: Partial<ChatConversation> = {}): ChatConversation =>
        conversation({
            id,
            mode: 'awaiting_human',
            handoff_at: at,
            visitor_waiting_since: at,
            last_message_at: at,
            ...overrides,
        });
    /** Taken and answered: nobody waits. */
    const answered = (id: string, overrides: Partial<ChatConversation> = {}): ChatConversation =>
        conversation({ id, mode: 'human', assigned_operator_id: 7, handoff_at: at, last_message_at: at, ...overrides });

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

    it('mints a ticket, opens the stream, bumps the ready epoch and seeds the waiting count on ready', () => {
        service.start(1);
        const source = openStream();
        expect(source.url).toBe('/chat/operator/v1/inbox/stream?ticket=t-1');
        expect(service.status()).toBe('open');
        expect(service.readyEpoch()).toBe(0);

        source.emit('ready', {}, '42');
        expect(service.readyEpoch()).toBe(1);
        httpMock.expectOne(badgesUrl).flush(badges(['c-1', 'c-2', 'c-3']));
        expect(service.waitingCount()).toBe(3);
    });

    it('seeds with one badges request per ready', () => {
        service.start(1);
        const source = openStream();
        source.emit('ready', {}, '1');
        httpMock.expectOne(badgesUrl).flush(badges(['c-1']));
        httpMock.expectNone(badgesUrl);

        source.emit('ready', {}, '2');
        httpMock.expectOne(badgesUrl).flush(badges(['c-1', 'c-2']));
        expect(service.waitingCount()).toBe(2);
    });

    it('adds and removes waiting ids from the after-state of conversation updates', () => {
        service.start(1);
        const source = openStream();
        source.emit('ready', {}, '1');
        httpMock.expectOne(badgesUrl).flush(badges(['c-1']));

        source.emit('conversation.updated', waiting('c-2'), '5');
        expect(service.waitingCount()).toBe(2);
        // An operator reply clears the wait; the row is in progress now.
        source.emit('conversation.updated', answered('c-1'), '6');
        expect(service.waitingCount()).toBe(1);
        // Released to the bot: nobody waits.
        source.emit('conversation.updated', conversation({ id: 'c-2', last_message_at: at }), '7');
        expect(service.waitingCount()).toBe(0);
        // An older snapshot is deduped before it can touch the count.
        source.emit('conversation.updated', waiting('c-1'), '4');
        expect(service.waitingCount()).toBe(0);
    });

    it('counts a taken conversation whose visitor wrote again as waiting', () => {
        service.start(1);
        const source = openStream();
        source.emit('ready', {}, '1');
        httpMock.expectOne(badgesUrl).flush(badges([]));

        source.emit('conversation.updated', answered('c-1'), '5');
        expect(service.waitingCount()).toBe(0);
        source.emit('conversation.updated', answered('c-1', { visitor_waiting_since: at }), '6');
        expect(service.waitingCount()).toBe(1);
        expect(service.waitingCountFor(null, 7)).toBe(1);
    });

    it('counts waiting conversations per desk from the seed and from updates', () => {
        service.start(1);
        const source = openStream();
        source.emit('ready', {}, '1');
        httpMock.expectOne(badgesUrl).flush({ waiting: [badge('c-1', 'b-1'), badge('c-2', 'b-2')] });
        expect(service.waitingByBinding()).toEqual({ 'b-1': 1, 'b-2': 1 });

        source.emit('conversation.updated', waiting('c-3', { binding_id: 'b-1' }), '5');
        source.emit('conversation.updated', answered('c-2', { binding_id: 'b-2' }), '6');
        expect(service.waitingByBinding()).toEqual({ 'b-1': 2 });
        expect(service.waitingCount()).toBe(2);

        service.stop();
        expect(service.waitingByBinding()).toEqual({});
    });

    it('counts per desk, across desks and for Mine by the holder, following take over live', () => {
        service.start(1);
        const source = openStream();
        source.emit('ready', {}, '1');
        httpMock.expectOne(badgesUrl).flush({
            waiting: [badge('c-1', 'b-1'), badge('c-2', 'b-1', 7), badge('c-3', 'b-2', 7), badge('c-4', 'b-2', 8)],
        });

        expect(service.waitingCountFor(null, null)).toBe(4);
        expect(service.waitingCountFor('b-1', null)).toBe(2);
        expect(service.waitingCountFor(null, 7)).toBe(2);
        expect(service.waitingCountFor('b-2', 7)).toBe(1);
        expect(service.waitingCountFor('b-3', null)).toBe(0);

        // Taking over keeps the wait and moves it into the holder's Mine count.
        source.emit('conversation.updated', waiting('c-1', { mode: 'human', assigned_operator_id: 7 }), '5');
        expect(service.waitingCountFor(null, 7)).toBe(3);
        expect(service.waitingCountFor('b-1', null)).toBe(2);
    });

    it('never counts a test conversation as waiting', () => {
        service.start(1);
        const source = openStream();
        source.emit('ready', {}, '1');
        httpMock.expectOne(badgesUrl).flush(badges([]));
        source.emit('conversation.updated', waiting('c-9', { is_test: true }), '5');
        expect(service.waitingCount()).toBe(0);
        expect(service.waitingByBinding()).toEqual({});
    });

    it('replays updates that arrive while the seed is in flight over the seed', () => {
        service.start(1);
        const source = openStream();
        source.emit('ready', {}, '1');
        const seed = httpMock.expectOne(badgesUrl);

        source.emit('conversation.updated', answered('c-1'), '5');
        source.emit('conversation.updated', waiting('c-8'), '6');
        source.emit('conversation.updated', waiting('c-9'), '7');
        source.emit('conversation.updated', waiting('c-2', { mode: 'human', assigned_operator_id: 7 }), '8');
        seed.flush(badges(['c-1', 'c-2', 'c-3']));

        // c-1 stopped waiting after the snapshot listed it; c-8 and c-9 started without being in it.
        // Without the replay the count would read 3 (snapshot only); a plain union would read 5.
        expect(service.waitingCount()).toBe(4);
        // The replayed after-state also wins on who holds a listed conversation.
        expect(service.waitingCountFor(null, 7)).toBe(1);
    });

    it('ignores a seed from an earlier ready once a newer one starts', () => {
        service.start(1);
        const source = openStream();
        source.emit('ready', {}, '1');
        const stale = httpMock.expectOne(badgesUrl);
        source.emit('ready', {}, '2');

        expect(stale.cancelled).toBe(true);
        httpMock.expectOne(badgesUrl).flush(badges(['c-1']));
        expect(service.waitingCount()).toBe(1);
    });

    it('ignores a seed from a previous org', () => {
        service.start(1);
        openStream('t-1').emit('ready', {}, '1');
        const stale = httpMock.expectOne(badgesUrl);
        service.start(2);

        expect(stale.cancelled).toBe(true);
        openStream('t-2').emit('ready', {}, '1');
        httpMock.expectOne(badgesUrl).flush(badges([]));
        expect(service.waitingCount()).toBe(0);
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

    it('keeps the previous waiting count when the seed fails, and keeps applying updates', () => {
        service.start(1);
        const source = openStream();
        source.emit('ready', {}, '1');
        httpMock.expectOne(badgesUrl).flush(badges(['c-1', 'c-2', 'c-3']));

        source.emit('ready', {}, '2');
        httpMock.expectOne(badgesUrl).flush('boom', { status: 500, statusText: 'Server Error' });
        expect(service.waitingCount()).toBe(3);

        source.emit('conversation.updated', answered('c-1'), '5');
        expect(service.waitingCount()).toBe(2);
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
            author_user_id: null,
            author_name: null,
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
        expect(service.waitingCount()).toBe(0);
    });
});
