import { HttpErrorResponse } from '@angular/common/http';
import { computed, inject, Injectable, signal } from '@angular/core';
import { Subject, Subscription } from 'rxjs';

import { ChatConversation, ChatInboxBadge, ChatInboxMessageEvent } from '../models/chat.model';
import { belongsTo } from '../utils/inbox-merge.util';
import { ChatApiService } from './chat-api.service';
import { TabLeadership } from './tab-leadership';

export type ChatStreamStatus = 'closed' | 'connecting' | 'open' | 'reconnecting';

const BASE_RECONNECT_DELAY_MS = 1000;
const MAX_RECONNECT_DELAY_MS = 30000;

/** Where a waiting conversation waits and who holds it, so the count can be taken per desk and for Mine. */
type WaitingPlacement = Omit<ChatInboxBadge, 'id'>;

/** A stream event, as every tab applies it. */
type InboxStreamEvent =
    | { kind: 'ready' }
    | { kind: 'conversation.updated'; row: ChatConversation; lastEventId: string }
    | { kind: 'message.created'; event: ChatInboxMessageEvent };

/** What the leader tab relays to the other tabs on the same org, plus the handshake of a tab that joins. */
type InboxRelayMessage =
    | InboxStreamEvent
    | { kind: 'status'; status: ChatStreamStatus }
    | { kind: 'hello' }
    | { kind: 'welcome'; status: ChatStreamStatus };

/**
 * The org-wide inbox stream (`GET /chat/operator/v1/inbox/stream`). Started by the sidenav for the active org,
 * so the waiting badge is live on every page; the chat page reads the same stream.
 *
 * Every (re)connect mints a fresh single-use ticket and opens without a cursor: the service only reads
 * `Last-Event-ID` from a header `EventSource` cannot set once the ticket is consumed. Consumers therefore
 * refetch their REST state whenever `readyEpoch` changes, which is the `ready` event the server sends after
 * each open.
 *
 * One tab per browser and org holds the stream (see `TabLeadership`): an open `EventSource` per tab would use up the
 * browser's six HTTP/1.1 connections per origin and stall every other request. The leader relays each event to the
 * other tabs, which apply it exactly as the leader does; when the leader closes, the next tab opens the stream and
 * its `ready` reaches them all.
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
    private readonly tabs = new TabLeadership<InboxRelayMessage>();
    /** A tab that joined behind a leader, until the leader answers with its status. */
    private awaitingWelcome = false;
    /** The user and org whose stream this tab follows, which is also its group among the tabs; null when stopped. */
    private groupName: string | null = null;
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

    /**
     * Follows the stream for `userId` in `orgId`; a different user (a logout and login in another tab) or org restarts
     * it, so tabs never share one user's stream with another.
     */
    start(orgId: number, userId: number): void {
        const groupName = `epicstaff-chat-inbox:${userId}:${orgId}`;
        if (this.groupName === groupName && this.status() !== 'closed') return;
        this.stop();
        this.groupName = groupName;
        this.status.set('connecting');
        this.tabs.join(
            groupName,
            () => this.lead(),
            (message) => this.receive(message)
        );
        if (!this.tabs.isLeader) {
            this.awaitingWelcome = true;
            this.tabs.post({ kind: 'hello' });
        }
    }

    stop(): void {
        this.tabs.leave();
        this.awaitingWelcome = false;
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
        this.groupName = null;
        this.reconnectAttempts = 0;
        this.highestSeqByConversation.clear();
        this.waiting.set(new Map());
        this.status.set('closed');
    }

    private lead(): void {
        this.awaitingWelcome = false;
        this.connect();
    }

    private connect(): void {
        this.setStatus(this.reconnectAttempts ? 'reconnecting' : 'connecting');
        const epoch = ++this.connectEpoch;
        this.ticketSubscription?.unsubscribe();
        this.ticketSubscription = this.chatApi.getInboxTicket().subscribe({
            next: ({ ticket }) => {
                if (epoch !== this.connectEpoch) return;
                this.open(ticket, epoch);
            },
            error: (error: unknown) => {
                if (epoch !== this.connectEpoch) return;
                // A 401 that outlived the token refresh, or a 403: the chat service refuses this user, which a restart or
                // a key rotation there can cause for a while. Retry slowly rather than give up until a page reload.
                const isRefused = error instanceof HttpErrorResponse && (error.status === 401 || error.status === 403);
                this.scheduleReconnect(isRefused ? MAX_RECONNECT_DELAY_MS : null);
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
            this.setStatus('open');
        };
        source.addEventListener('ready', () => {
            if (live()) this.relay({ kind: 'ready' });
        });
        source.addEventListener('conversation.updated', (event: MessageEvent<string>) => {
            if (!live()) return;
            const row = JSON.parse(event.data) as ChatConversation;
            this.relay({ kind: 'conversation.updated', row, lastEventId: event.lastEventId });
        });
        source.addEventListener('message.created', (event: MessageEvent<string>) => {
            if (!live()) return;
            this.relay({ kind: 'message.created', event: JSON.parse(event.data) as ChatInboxMessageEvent });
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

    private scheduleReconnect(fixedDelay: number | null = null): void {
        this.setStatus('reconnecting');
        const exponential = BASE_RECONNECT_DELAY_MS * 2 ** this.reconnectAttempts;
        const delay = fixedDelay ?? Math.min(exponential + Math.random() * 0.1 * exponential, MAX_RECONNECT_DELAY_MS);
        this.reconnectAttempts++;
        this.reconnectTimer = setTimeout(() => {
            this.reconnectTimer = null;
            if (this.groupName !== null) this.connect();
        }, delay);
    }

    /** The leader applies each stream event here and hands it to the other tabs. */
    private relay(message: InboxStreamEvent): void {
        this.tabs.post(message);
        this.apply(message);
    }

    private setStatus(status: ChatStreamStatus): void {
        this.status.set(status);
        if (this.tabs.isLeader) this.tabs.post({ kind: 'status', status });
    }

    private receive(message: InboxRelayMessage): void {
        if (this.tabs.isLeader) {
            if (message.kind === 'hello') this.tabs.post({ kind: 'welcome', status: this.status() });
            // Anything else is from a leader that has since let go: this tab's own stream supersedes it.
            return;
        }
        switch (message.kind) {
            case 'hello':
                return;
            case 'welcome':
                if (!this.awaitingWelcome) return;
                this.awaitingWelcome = false;
                this.status.set(message.status);
                // The stream is live for this tab from now: the same as a `ready` of its own.
                if (message.status === 'open') this.apply({ kind: 'ready' });
                return;
            case 'status':
                this.status.set(message.status);
                return;
            default:
                this.apply(message);
        }
    }

    /** One stream event, the same in the leader and in the tabs it relays to. */
    private apply(message: InboxStreamEvent): void {
        switch (message.kind) {
            case 'ready':
                this.awaitingWelcome = false;
                this.readyEpoch.update((value) => value + 1);
                this.seedWaiting(this.connectEpoch);
                return;
            case 'conversation.updated':
                this.applyConversationUpdate(message.row, message.lastEventId);
                return;
            case 'message.created':
                this.messageCreated$.next(message.event);
        }
    }

    private applyConversationUpdate(row: ChatConversation, lastEventId: string): void {
        const seq = Number(lastEventId);
        // An unusable id (missing or non-numeric) cannot be ordered: pass the update through unrecorded.
        if (Number.isFinite(seq) && lastEventId !== '') {
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
