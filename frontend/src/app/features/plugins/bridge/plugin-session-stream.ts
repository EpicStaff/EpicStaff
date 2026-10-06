import { InjectionToken } from '@angular/core';
import { TERMINAL_SESSION_STATUSES } from '@shared/models';
import { Observable, Subscription } from 'rxjs';

import {
    BridgeSessionMessageData,
    BridgeSessionStatusData,
    BridgeSubscriptionClosedData,
    isRecord,
} from './bridge-protocol';

/** Opens an `EventSource`; replaced in tests (jsdom has none). */
export type EventSourceFactory = (url: string) => EventSource;

export const PLUGIN_EVENT_SOURCE_FACTORY = new InjectionToken<EventSourceFactory>('PLUGIN_EVENT_SOURCE_FACTORY', {
    providedIn: 'root',
    factory: () => (url: string) => new EventSource(url),
});

/** Reconnects after a stream error before the subscription is closed with `error`. */
const MAX_RECONNECT_ATTEMPTS = 3;
const BASE_RECONNECT_DELAY_MS = 1000;

/**
 * How long a stream stays open after a final status. The backend publishes the last messages
 * (e.g. `graph_end`) and the status through different Redis paths, so a message may arrive
 * just after the status that ends the session.
 */
export const TERMINAL_GRACE_MS = 3000;

const TERMINAL_STATUSES: ReadonlySet<string> = TERMINAL_SESSION_STATUSES;

export interface PluginSessionStreamOptions {
    sessionId: number;
    /** A fresh single-use SSE ticket per connection attempt. */
    fetchTicket: () => Observable<string>;
    streamUrl: (sessionId: number, ticket: string) => string;
    createEventSource: EventSourceFactory;
    onMessage: (data: BridgeSessionMessageData) => void;
    onStatus: (data: BridgeSessionStatusData) => void;
    /** Called once when the stream closes on its own; not called after `close()`. */
    onClosed: (data: BridgeSubscriptionClosedData) => void;
}

/**
 * One run-session SSE stream for one bridge subscription.
 *
 * Deliberately not the root `RunSessionSSEService`: that singleton serves the running-session
 * page, and a plugin page may hold several subscriptions. Each connection takes its own SSE
 * ticket. Messages are de-duplicated by `uuid` because a reconnect replays the session's
 * history. A final status closes the stream {@link TERMINAL_GRACE_MS} after it is relayed.
 */
export class PluginSessionStream {
    private eventSource: EventSource | null = null;
    private ticketSubscription: Subscription | null = null;
    private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
    private reconnectAttempts = 0;
    private closed = false;
    private finishTimer: ReturnType<typeof setTimeout> | null = null;
    private readonly seenMessageIds = new Set<string>();

    constructor(private readonly options: PluginSessionStreamOptions) {}

    start(): void {
        if (this.closed || this.eventSource || this.ticketSubscription) return;
        const subscription = this.options.fetchTicket().subscribe({
            next: (ticket) => {
                this.ticketSubscription = null;
                if (!this.closed && !this.eventSource) this.open(ticket);
            },
            error: () => {
                this.ticketSubscription = null;
                this.handleFailure();
            },
        });
        // A ticket source that answered synchronously has already finished.
        if (!subscription.closed) this.ticketSubscription = subscription;
    }

    /** Closes the stream without notifying `onClosed`. Safe to call more than once. */
    close(): void {
        this.closed = true;
        if (this.finishTimer !== null) {
            clearTimeout(this.finishTimer);
            this.finishTimer = null;
        }
        this.teardownConnection();
    }

    private open(ticket: string): void {
        const eventSource = this.options.createEventSource(this.options.streamUrl(this.options.sessionId, ticket));
        this.eventSource = eventSource;
        eventSource.onopen = () => {
            this.reconnectAttempts = 0;
        };
        eventSource.addEventListener('messages', (event: MessageEvent) => this.handleMessage(event));
        eventSource.addEventListener('status', (event: MessageEvent) => this.handleStatus(event));
        eventSource.addEventListener('fatal-error', () => this.handleFailure());
        eventSource.onerror = () => this.handleFailure();
    }

    private handleMessage(event: MessageEvent): void {
        if (this.closed) return;
        const raw = parseJson(event.data);
        if (!isRecord(raw) || !this.isOwnSession(raw)) return;

        const uuid = typeof raw['uuid'] === 'string' ? raw['uuid'] : null;
        if (uuid !== null) {
            if (this.seenMessageIds.has(uuid)) return;
            this.seenMessageIds.add(uuid);
        }

        const messageData = raw['message_data'];
        const messageType = isRecord(messageData) ? messageData['message_type'] : null;
        const createdAt = raw['created_at'] ?? raw['timestamp'];
        this.options.onMessage({
            message_type: typeof messageType === 'string' ? messageType : null,
            name: typeof raw['name'] === 'string' ? raw['name'] : '',
            created_at: typeof createdAt === 'string' ? createdAt : null,
            message_data: messageData ?? null,
        });
    }

    private handleStatus(event: MessageEvent): void {
        if (this.closed) return;
        const raw = parseJson(event.data);
        if (!isRecord(raw) || !this.isOwnSession(raw) || typeof raw['status'] !== 'string') return;

        const status = raw['status'];
        this.options.onStatus({ status });
        if (TERMINAL_STATUSES.has(status) && this.finishTimer === null) {
            this.finishTimer = setTimeout(() => this.finish({ reason: 'ended' }), TERMINAL_GRACE_MS);
        }
    }

    private isOwnSession(raw: Record<string, unknown>): boolean {
        const sessionId = raw['session_id'];
        return sessionId === undefined || sessionId === null || String(sessionId) === String(this.options.sessionId);
    }

    private handleFailure(): void {
        if (this.closed) return;
        if (this.finishTimer !== null) {
            // The session already ended; nothing worth reconnecting for.
            this.finish({ reason: 'ended' });
            return;
        }
        this.teardownConnection();
        if (this.reconnectAttempts >= MAX_RECONNECT_ATTEMPTS) {
            this.finish({ reason: 'error' });
            return;
        }
        const delay = BASE_RECONNECT_DELAY_MS * 2 ** this.reconnectAttempts;
        this.reconnectAttempts++;
        this.reconnectTimer = setTimeout(() => {
            this.reconnectTimer = null;
            this.start();
        }, delay);
    }

    private finish(data: BridgeSubscriptionClosedData): void {
        if (this.closed) return;
        this.close();
        this.options.onClosed(data);
    }

    private teardownConnection(): void {
        this.ticketSubscription?.unsubscribe();
        this.ticketSubscription = null;
        if (this.reconnectTimer !== null) {
            clearTimeout(this.reconnectTimer);
            this.reconnectTimer = null;
        }
        if (this.eventSource) {
            this.eventSource.onopen = null;
            this.eventSource.onerror = null;
            this.eventSource.close();
            this.eventSource = null;
        }
    }
}

function parseJson(data: unknown): unknown {
    if (typeof data !== 'string') return null;
    try {
        return JSON.parse(data) as unknown;
    } catch {
        return null;
    }
}
