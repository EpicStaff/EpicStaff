import { inject, Injectable, signal } from '@angular/core';
import { EMPTY, expand, map, Observable, Subject, Subscription } from 'rxjs';

import { ChatConversation, ChatConversationPage, ChatInboxMessageEvent } from '../models/chat.model';
import { ChatApiService } from './chat-api.service';

export type ChatStreamStatus = 'closed' | 'connecting' | 'open' | 'reconnecting';

const BASE_RECONNECT_DELAY_MS = 1000;
const MAX_RECONNECT_DELAY_MS = 30000;

/**
 * The org-wide inbox stream (`GET /chat/operator/v1/inbox/stream`). Started by the sidenav for the active org,
 * so the awaiting badge is live on every page; the chat page reads the same stream.
 *
 * Every (re)connect mints a fresh single-use ticket and opens without a cursor: the service only reads
 * `Last-Event-ID` from a header `EventSource` cannot set once the ticket is consumed. Consumers therefore
 * refetch their REST state whenever `readyEpoch` changes, which is the `ready` event the server sends after
 * each open.
 */
@Injectable({ providedIn: 'root' })
export class ChatInboxStreamService {
    readonly status = signal<ChatStreamStatus>('closed');
    /** Bumped on every `ready`: the stream is live from now, so REST state loaded after this is complete. */
    readonly readyEpoch = signal(0);
    readonly awaitingCount = signal(0);
    /** Awaiting conversations per binding id, for the bindings list; a binding with none is absent. */
    readonly awaitingByBinding = signal<Readonly<Record<string, number>>>({});
    /** Snapshots that are older (lower seq) than one already seen for the same conversation are dropped here. */
    readonly conversationUpdated$ = new Subject<ChatConversation>();
    readonly messageCreated$ = new Subject<ChatInboxMessageEvent>();

    private readonly chatApi = inject(ChatApiService);
    private orgId: number | null = null;
    private eventSource: EventSource | null = null;
    private ticketSubscription: Subscription | null = null;
    private seedSubscription: Subscription | null = null;
    private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
    private reconnectAttempts = 0;
    private connectEpoch = 0;
    private readonly highestSeqByConversation = new Map<string, number>();
    /** Awaiting conversation id → its binding id. */
    private awaiting = new Map<string, string>();
    /**
     * Updates seen while a seed is in flight, by conversation id: its binding id when awaiting, null when not.
     * Replayed over the seed when it lands.
     */
    private updatesDuringSeed: Map<string, string | null> | null = null;

    start(orgId: number): void {
        if (this.orgId === orgId && this.status() !== 'closed') return;
        this.stop();
        this.orgId = orgId;
        this.connect();
    }

    stop(): void {
        this.connectEpoch++;
        this.ticketSubscription?.unsubscribe();
        this.ticketSubscription = null;
        this.seedSubscription?.unsubscribe();
        this.seedSubscription = null;
        this.updatesDuringSeed = null;
        if (this.reconnectTimer) clearTimeout(this.reconnectTimer);
        this.reconnectTimer = null;
        this.eventSource?.close();
        this.eventSource = null;
        this.orgId = null;
        this.reconnectAttempts = 0;
        this.highestSeqByConversation.clear();
        this.publishAwaiting(new Map());
        this.status.set('closed');
    }

    private connect(): void {
        this.status.set(this.reconnectAttempts ? 'reconnecting' : 'connecting');
        const epoch = ++this.connectEpoch;
        this.ticketSubscription?.unsubscribe();
        this.ticketSubscription = this.chatApi.getInboxTicket().subscribe({
            next: ({ ticket }) => {
                if (epoch !== this.connectEpoch) return;
                this.open(ticket, epoch);
            },
            error: () => {
                if (epoch === this.connectEpoch) this.scheduleReconnect();
            },
        });
    }

    private open(ticket: string, epoch: number): void {
        const source = new EventSource(this.chatApi.inboxStreamUrl(ticket));
        this.eventSource = source;
        const live = (): boolean => epoch === this.connectEpoch;

        source.onopen = () => {
            if (!live()) return;
            this.reconnectAttempts = 0;
            this.status.set('open');
        };
        source.addEventListener('ready', () => {
            if (!live()) return;
            this.readyEpoch.update((value) => value + 1);
            this.seedAwaiting(epoch);
        });
        source.addEventListener('conversation.updated', (event: MessageEvent<string>) => {
            if (!live()) return;
            const row = JSON.parse(event.data) as ChatConversation;
            const seq = Number(event.lastEventId);
            // An unusable id (missing or non-numeric) cannot be ordered: pass the update through unrecorded.
            if (Number.isFinite(seq) && event.lastEventId !== '') {
                if (seq <= (this.highestSeqByConversation.get(row.id) ?? 0)) return;
                this.highestSeqByConversation.set(row.id, seq);
            }
            this.conversationUpdated$.next(row);
            // Test conversations never count as waiting: the seed (section=human) leaves them out too.
            const awaitingOn = row.mode === 'awaiting_human' && !row.is_test ? row.binding_id : null;
            this.applyAwaiting(this.awaiting, row.id, awaitingOn);
            this.updatesDuringSeed?.set(row.id, awaitingOn);
            this.publishAwaiting(this.awaiting);
        });
        source.addEventListener('message.created', (event: MessageEvent<string>) => {
            if (!live()) return;
            this.messageCreated$.next(JSON.parse(event.data) as ChatInboxMessageEvent);
        });
        source.addEventListener('reset', () => {
            // Only possible with a cursor, which this client never sends; `ready` follows and triggers the refetch.
            console.warn('Chat inbox stream reset');
        });
        source.onerror = () => {
            if (!live()) return;
            // A 401 (consumed ticket), a 429 (stream slot limit) or a network drop all land here; the browser
            // gives no status, so every case gets the same fresh-ticket reconnect with backoff.
            source.close();
            this.eventSource = null;
            this.scheduleReconnect();
        };
    }

    private scheduleReconnect(): void {
        this.status.set('reconnecting');
        const exponential = BASE_RECONNECT_DELAY_MS * 2 ** this.reconnectAttempts;
        const delay = Math.min(exponential + Math.random() * 0.1 * exponential, MAX_RECONNECT_DELAY_MS);
        this.reconnectAttempts++;
        this.reconnectTimer = setTimeout(() => {
            this.reconnectTimer = null;
            if (this.orgId !== null) this.connect();
        }, delay);
    }

    /**
     * Seeds the badge from every page of awaiting conversations (the human section filtered to `awaiting_human`).
     * Updates that land meanwhile are replayed over the seed rather than unioned with it, so they can also remove
     * an id: the last update per id during the seed wins over the pages, and later events are applied live.
     */
    private seedAwaiting(epoch: number): void {
        this.seedSubscription?.unsubscribe();
        const updatesDuringThisSeed = new Map<string, string | null>();
        this.updatesDuringSeed = updatesDuringThisSeed;
        const seeded = new Map<string, string>();
        const fetchPage = (cursor: string | null): Observable<{ page: ChatConversationPage; cursor: string | null }> =>
            this.chatApi
                .getConversations({ section: 'human', mode: 'awaiting_human', binding: null, cursor })
                .pipe(map((page) => ({ page, cursor })));
        this.seedSubscription = fetchPage(null)
            .pipe(
                // A repeated cursor would loop forever: treat it as the last page.
                expand(({ page, cursor }) =>
                    page.next_cursor && page.next_cursor !== cursor ? fetchPage(page.next_cursor) : EMPTY
                )
            )
            .subscribe({
                next: ({ page }) => page.results.forEach((item) => seeded.set(item.id, item.binding_id)),
                // Keep the last known badge: a failed seed (403, network, 5xx) must not blank or break it.
                error: () => {
                    if (this.updatesDuringSeed === updatesDuringThisSeed) this.updatesDuringSeed = null;
                },
                complete: () => {
                    if (epoch !== this.connectEpoch || this.updatesDuringSeed !== updatesDuringThisSeed) return;
                    updatesDuringThisSeed.forEach((awaitingOn, id) => this.applyAwaiting(seeded, id, awaitingOn));
                    this.updatesDuringSeed = null;
                    this.publishAwaiting(seeded);
                },
            });
    }

    private applyAwaiting(awaiting: Map<string, string>, id: string, bindingId: string | null): void {
        if (bindingId) awaiting.set(id, bindingId);
        else awaiting.delete(id);
    }

    private publishAwaiting(awaiting: Map<string, string>): void {
        this.awaiting = awaiting;
        const byBinding: Record<string, number> = {};
        awaiting.forEach((bindingId) => (byBinding[bindingId] = (byBinding[bindingId] ?? 0) + 1));
        this.awaitingCount.set(awaiting.size);
        this.awaitingByBinding.set(byBinding);
    }
}
