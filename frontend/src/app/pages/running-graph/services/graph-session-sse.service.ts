import { inject, Injectable, signal } from '@angular/core';
import { GraphSessionStatus } from '@shared/models';
import { Subscription } from 'rxjs';

import { SseTicketService } from '../../../services/auth/sse-ticket.service';
import { ConfigService } from '../../../services/config';
import { Memory } from '../components/memory-sidebar/models/memory.model';
import { GraphMessage } from '../models/graph-session-message.model';

@Injectable({
    providedIn: 'root',
})
export class RunSessionSSEService {
    private configService = inject(ConfigService);
    private sseTicketService = inject(SseTicketService);

    private eventSource: EventSource | null = null;
    private currentSessionId: string | null = null;
    private reconnectTimeout: ReturnType<typeof setTimeout> | null = null;
    private connectEpoch = 0;
    private ticketSubscription: Subscription | null = null;

    // Signals
    private messagesSignal = signal<GraphMessage[]>([]);
    private statusSignal = signal<GraphSessionStatus>(GraphSessionStatus.RUNNING);
    private memoriesSignal = signal<Memory[]>([]);
    private streamOpen = signal(false);
    private connectionStatusSignal = signal<
        'connected' | 'connecting' | 'disconnected' | 'reconnecting' | 'manually_disconnected'
    >('disconnected');
    private nodeNameFilterSignal = signal<string | null>(null);
    public readonly nodeNameFilter = this.nodeNameFilterSignal.asReadonly();
    public readonly isStreaming = this.streamOpen.asReadonly();
    public readonly messages = this.messagesSignal.asReadonly();
    public readonly status = this.statusSignal.asReadonly();
    public readonly memories = this.memoriesSignal.asReadonly();
    public readonly connectionStatus = this.connectionStatusSignal.asReadonly();

    private readonly TERMINAL_STATUSES: ReadonlySet<GraphSessionStatus> = new Set([
        GraphSessionStatus.ENDED,
        GraphSessionStatus.ERROR,
        GraphSessionStatus.STOP,
        GraphSessionStatus.EXPIRED,
    ]);

    public setStatus(status: GraphSessionStatus): void {
        const current = this.statusSignal();
        // Terminal status is an authoritative end of the session. Don't let late SSE
        // status events or get-updates responses downgrade it back to run/pending.
        // Transitions between terminal statuses (ENDED → ERROR/STOP) are allowed
        // so the API can refine the final status.
        if (this.TERMINAL_STATUSES.has(current) && !this.TERMINAL_STATUSES.has(status)) {
            return;
        }
        this.statusSignal.set(status);
    }

    // Reconnection configuration
    private reconnectAttempts = 0;
    private readonly maxReconnectAttempts = 5;
    private readonly baseReconnectDelayMs = 1000;
    private readonly maxReconnectDelayMs = 30000;
    private isManualDisconnect = false;

    private get apiUrl(): string {
        const baseUrl = this.configService.apiUrl;

        const url = `${baseUrl}run-session/subscribe/${this.currentSessionId}/`;

        return url;
    }

    public setNodeNameFilter(nodeName: string | null): void {
        this.nodeNameFilterSignal.set(nodeName);
    }

    public startStream(sessionId: string): void {
        if (this.currentSessionId === sessionId && this.eventSource) return;
        this.cleanup();
        this.currentSessionId = sessionId;
        this.isManualDisconnect = false;
        this.connect(sessionId);
    }

    public resumeStream(): void {
        if (!this.currentSessionId) return;
        this.isManualDisconnect = false;
        this.connect(this.currentSessionId);
    }

    public stopStream(): void {
        this.isManualDisconnect = true;
        this.disconnect();
        this.connectionStatusSignal.set('manually_disconnected');
    }

    /**
     * Full reset of the stream and its buffered messages/memories. Used when the displayed
     * session changes: stopStream() alone leaves currentSessionId and the signals populated
     * from the previous session. The status signal is deliberately preserved —
     * loadData() sets the incoming session's real status, and forcing RUNNING here would
     * briefly advertise a completed session as running (Stop button).
     */
    public reset(): void {
        this.cleanup(false);
    }

    private connect(sessionId: string): void {
        if (this.eventSource) {
            console.warn('SSE already started');
            return;
        }

        this.connectionStatusSignal.set('connecting');

        const epoch = ++this.connectEpoch;
        this.ticketSubscription?.unsubscribe();
        this.ticketSubscription = this.sseTicketService.fetchTicket().subscribe({
            next: (ticket) => {
                // A ticket that resolves after stopStream() or a session switch must not
                // open a stream — apiUrl is built from currentSessionId, so it would target the
                // previous (still running) session and keep streaming it into the new session's view.
                if (epoch !== this.connectEpoch || this.isManualDisconnect || this.currentSessionId !== sessionId) {
                    return;
                }
                this.openEventSource(ticket);
            },
            error: (err) => {
                if (epoch !== this.connectEpoch) return;
                console.error('Failed to fetch SSE ticket:', err);
                this.handleConnectionLoss();
            },
        });
    }

    private openEventSource(ticket: string): void {
        const streamSessionId = this.currentSessionId;
        const eventSourceUrl = `${this.apiUrl}?ticket=${encodeURIComponent(ticket)}`;
        this.eventSource = new EventSource(eventSourceUrl);

        this.eventSource.onopen = () => {
            if (streamSessionId !== this.currentSessionId) return;
            this.reconnectAttempts = 0;
            this.streamOpen.set(true);
            this.connectionStatusSignal.set('connected');
        };

        this.eventSource.onmessage = (event) => {
            if (streamSessionId !== this.currentSessionId) return;
            console.warn('Unnamed event received:', event.data);
        };

        this.eventSource.addEventListener('messages', (event: MessageEvent) => {
            if (streamSessionId !== this.currentSessionId) return;
            const raw = JSON.parse(event.data);

            const activeFilter = this.nodeNameFilterSignal();
            if (activeFilter && raw.name !== activeFilter) {
                return;
            }

            if (raw.session_id != null && String(raw.session_id) !== String(streamSessionId)) {
                return;
            }

            const msg: GraphMessage = {
                id: raw.id,
                uuid: raw.uuid,
                session: raw.session_id,
                name: raw.name,
                execution_order: raw.execution_order,
                created_at: raw.created_at || raw.timestamp,
                message_data: raw.message_data,
                metadata: raw.metadata || {},
            };

            const messagesList = this.messages();
            const exists = messagesList.some((m) => m.uuid === msg.uuid);
            if (!exists) {
                messagesList.push(msg);
                messagesList.sort((a, b) => new Date(a.created_at).getTime() - new Date(b.created_at).getTime());
                this.messagesSignal.set([...messagesList]);
            }
        });

        this.eventSource.addEventListener('status', (event: MessageEvent) => {
            if (streamSessionId !== this.currentSessionId) return;
            const statusData = JSON.parse(event.data);
            this.setStatus(statusData.status as GraphSessionStatus);
        });

        this.eventSource.addEventListener('memory', (event: MessageEvent) => {
            if (streamSessionId !== this.currentSessionId) return;
            const memory = JSON.parse(event.data) as Memory;
            const memoriesList = this.memories();
            const existingIndex = memoriesList.findIndex((m) => m.id === memory.id);

            if (existingIndex !== -1) {
                // Update existing memory
                memoriesList[existingIndex] = memory;
            } else {
                // Add new memory
                memoriesList.push(memory);
            }

            this.memoriesSignal.set([...memoriesList]);
        });

        this.eventSource.addEventListener('memory-delete', (event: MessageEvent) => {
            if (streamSessionId !== this.currentSessionId) return;
            const memory = JSON.parse(event.data);
            const memoriesList = this.memories();
            const existingIndex = memoriesList.findIndex((m) => m.id === memory);

            if (existingIndex !== -1) {
                // Delete existing memory
                memoriesList.splice(existingIndex, 1);
                this.memoriesSignal.set([...memoriesList]);
            }
        });

        this.eventSource.addEventListener('fatal-error', () => {
            if (streamSessionId !== this.currentSessionId) return;
            console.error('Fatal SSE error received');
            if (this.eventSource) {
                this.eventSource.close();
                this.eventSource = null;
            }
            this.handleConnectionLoss();
        });

        this.eventSource.onerror = (err) => {
            if (streamSessionId !== this.currentSessionId) return;
            console.error('SSE error:', err);
            if (this.eventSource) {
                this.eventSource.close();
                this.eventSource = null;
            }
            this.handleConnectionLoss();
        };
    }

    private handleConnectionLoss(): void {
        if (this.isManualDisconnect) {
            return;
        }

        this.connectionStatusSignal.set('reconnecting');
        this.streamOpen.set(false);

        if (this.reconnectAttempts >= this.maxReconnectAttempts) {
            console.error(`Max SSE reconnect attempts (${this.maxReconnectAttempts}) reached. Giving up.`);
            this.finalDisconnect();
            return;
        }

        this.reconnectAttempts++;
        const delay = this.calculateReconnectDelay();

        this.reconnectTimeout = setTimeout(() => {
            if (!this.isManualDisconnect && this.currentSessionId) {
                this.connect(this.currentSessionId);
            }
        }, delay);
    }

    private calculateReconnectDelay(): number {
        // Exponential backoff with jitter to prevent thundering herd
        const exponentialDelay = this.baseReconnectDelayMs * Math.pow(2, this.reconnectAttempts - 1);
        const jitter = Math.random() * 0.1 * exponentialDelay; // 10% jitter
        const finalDelay = Math.min(exponentialDelay + jitter, this.maxReconnectDelayMs);

        return finalDelay;
    }

    private finalDisconnect(): void {
        this.disconnect();
        this.connectionStatusSignal.set('disconnected');
    }

    private disconnect(): void {
        this.connectEpoch++;
        this.ticketSubscription?.unsubscribe();
        this.ticketSubscription = null;

        if (this.reconnectTimeout) {
            clearTimeout(this.reconnectTimeout);
            this.reconnectTimeout = null;
        }

        if (this.eventSource) {
            this.eventSource.close();
            this.eventSource = null;
        }

        this.streamOpen.set(false);
        this.connectionStatusSignal.set('disconnected');
    }

    private cleanup(resetStatus = true): void {
        this.connectEpoch++;
        this.ticketSubscription?.unsubscribe();
        this.ticketSubscription = null;

        if (this.reconnectTimeout) {
            clearTimeout(this.reconnectTimeout);
            this.reconnectTimeout = null;
        }

        if (this.eventSource) {
            this.eventSource.close();
            this.eventSource = null;
        }

        this.reconnectAttempts = 0;
        this.currentSessionId = null;
        this.isManualDisconnect = false;

        this.messagesSignal.set([]);
        this.memoriesSignal.set([]);
        if (resetStatus) {
            this.statusSignal.set(GraphSessionStatus.RUNNING);
        }
        this.streamOpen.set(false);
        this.connectionStatusSignal.set('disconnected');
    }
}
