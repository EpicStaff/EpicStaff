import { computed, inject, Injectable, signal } from '@angular/core';
import { Subject, Subscription } from 'rxjs';

import { ChatConversation, ChatInboxBadge, ChatInboxMessageEvent } from '../models/chat.model';
import { belongsTo } from '../utils/inbox-merge.util';
import { ChatApiService } from './chat-api.service';

export type ChatStreamStatus = 'closed' | 'connecting' | 'open' | 'reconnecting';

const BASE_RECONNECT_DELAY_MS = 1000;
const MAX_RECONNECT_DELAY_MS = 30000;

/** Where a waiting conversation waits and who holds it, so the count can be taken per desk and for Mine. */
type WaitingPlacement = Omit<ChatInboxBadge, 'id'>;

/**
 * The org-wide inbox stream (`GET /chat/operator/v1/inbox/stream`). Started by the sidenav for the active org,
 * so the waiting badge is live on every page; the chat page reads the same stream.
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
    /** Conversations waiting for a person across the org, tests never included: the sidenav badge. */
    readonly waitingCount = computed(() => this.waiting().size);
    /** Waiting conversations per desk (binding id), for the desk rail; a desk with none is absent. */
    readonly waitingByBinding = computed((): Readonly<Record<string, number>> => {
        const byBinding: Record<string, number> = {};
        this.waiting().forEach(({ binding_id }) => (byBinding[binding_id] = (byBinding[binding_id] ?? 0) + 1));
        return byBinding;
    });
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
    /** Waiting conversation id → where it waits: seeded from `/inbox/badges` on every `ready`, then kept live. */
    private readonly waiting = signal<ReadonlyMap<string, WaitingPlacement>>(new Map());
    /**
     * Updates seen while a seed is in flight, by conversation id: where it waits, or null when it does not.
     * Replayed over the seed when it lands.
     */
    private updatesDuringSeed: Map<string, WaitingPlacement | null> | null = null;

    /**
     * Waiting conversations on one desk, or on every desk for null; with `holderId` (Mine), only those that user
     * holds — a taken conversation waits again when its visitor writes. Reactive inside `computed`.
     */
    waitingCountFor(bindingId: string | null, holderId: number | null): number {
        let count = 0;
        this.waiting().forEach((placement) => {
            const isOnDesk = bindingId === null || placement.binding_id === bindingId;
            const isHeld = holderId === null || placement.assigned_operator_id === holderId;
            if (isOnDesk && isHeld) count++;
        });
        return count;
    }

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
        this.waiting.set(new Map());
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
            this.seedWaiting(epoch);
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
            // The after-state decides, by the Waiting section's own rule: tests never wait.
            const placement: WaitingPlacement | null = belongsTo(row, 'waiting', null)
                ? { binding_id: row.binding_id, assigned_operator_id: row.assigned_operator_id }
                : null;
            this.updatesDuringSeed?.set(row.id, placement);
            this.place(row.id, placement);
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
     * Seeds the waiting set from `/inbox/badges`, one request per `ready`. Updates that land meanwhile are replayed
     * over the seed rather than unioned with it, so they can also remove an id: the last update per id during the
     * seed wins over the response, and later events are applied live.
     */
    private seedWaiting(epoch: number): void {
        this.seedSubscription?.unsubscribe();
        const updatesDuringThisSeed = new Map<string, WaitingPlacement | null>();
        this.updatesDuringSeed = updatesDuringThisSeed;
        this.seedSubscription = this.chatApi.getInboxBadges().subscribe({
            next: ({ waiting }) => {
                if (epoch !== this.connectEpoch || this.updatesDuringSeed !== updatesDuringThisSeed) return;
                const seeded = new Map<string, WaitingPlacement>(
                    waiting.map(({ id, binding_id, assigned_operator_id }) => [
                        id,
                        { binding_id, assigned_operator_id },
                    ])
                );
                updatesDuringThisSeed.forEach((placement, id) => setPlacement(seeded, id, placement));
                this.updatesDuringSeed = null;
                this.waiting.set(seeded);
            },
            // Keep the last known counts: a failed seed (403, network, 5xx) must not blank or break them.
            error: () => {
                if (this.updatesDuringSeed === updatesDuringThisSeed) this.updatesDuringSeed = null;
            },
        });
    }

    /** One conversation's live after-state; most updates touch no waiting row, and those leave the set as it is. */
    private place(id: string, placement: WaitingPlacement | null): void {
        const current = this.waiting().get(id);
        const isUnchanged = placement
            ? current?.binding_id === placement.binding_id &&
              current.assigned_operator_id === placement.assigned_operator_id
            : !current;
        if (!isUnchanged) this.waiting.update((waiting) => setPlacement(new Map(waiting), id, placement));
    }
}

function setPlacement(
    waiting: Map<string, WaitingPlacement>,
    id: string,
    placement: WaitingPlacement | null
): Map<string, WaitingPlacement> {
    if (placement) waiting.set(id, placement);
    else waiting.delete(id);
    return waiting;
}
