import { inject, Injectable, signal } from '@angular/core';

import { SseTicketService } from '../../../services/auth/sse-ticket.service';
import { ConfigService } from '../../../services/config';
import { CollectionIndexingEventDto, CollectionStatus } from '../models/collection.model';
import { CollectionsStorageService } from './collections-storage.service';

export interface CollectionIndexingProgress {
    readonly done: number;
    readonly total: number;
    readonly collectionStatus: CollectionStatus;
    readonly currentDocumentConfigId: number | null;
    readonly currentDocumentStatus: string | null;
    readonly error: string | null;
}

interface IndexingConnection {
    eventSource: EventSource | null;
    reconnectTimeout: ReturnType<typeof setTimeout> | null;
    reconnectAttempts: number;
    manualDisconnect: boolean;
    /** Number of independent owners (tile, dialogs, ...) currently interested in this stream. */
    refCount: number;
}

const TERMINAL_COLLECTION_STATUSES: ReadonlySet<CollectionStatus> = new Set([
    CollectionStatus.COMPLETED,
    CollectionStatus.WARNING,
    CollectionStatus.FAILED,
]);

const MAX_RECONNECT_ATTEMPTS = 5;
const BASE_RECONNECT_DELAY_MS = 1000;
const MAX_RECONNECT_DELAY_MS = 30000;

/**
 * Tracks live collection indexing progress over Server-Sent Events.
 *
 * Connections are reference-counted per collectionId: multiple independent owners
 * (a collection tile, a rag-configuration dialog, the create-collection wizard, ...)
 * can all call `subscribe(id)`. The underlying EventSource opens on the 0→1 transition
 * and only closes once every owner has called a matching `unsubscribe(id)` (refCount
 * back to 0). This prevents one owner's teardown from killing a stream another owner
 * still needs.
 *
 * A terminal `collection_status` ('completed' | 'warning' | 'failed') force-closes the
 * connection and drops it regardless of outstanding refCount — the stream is done, so
 * lingering owners releasing later are harmless no-ops (`unsubscribe` on a missing
 * connection is a no-op). The same applies once reconnect attempts are exhausted.
 *
 * On every `indexing` event, the corresponding collection's `status` is patched
 * in `CollectionsStorageService` so the collection tile badge re-renders reactively.
 */
@Injectable({
    providedIn: 'root',
})
export class CollectionIndexingSSEService {
    private readonly progressSignal = signal<ReadonlyMap<number, CollectionIndexingProgress>>(new Map());
    public readonly progress = this.progressSignal.asReadonly();

    private readonly configService = inject(ConfigService);
    private readonly sseTicketService = inject(SseTicketService);
    private readonly collectionsStorageService = inject(CollectionsStorageService);

    private readonly connections = new Map<number, IndexingConnection>();

    /**
     * Registers interest in a collection's indexing stream. Increments the refCount;
     * opens the EventSource only on the 0→1 transition. Safe to call from multiple
     * independent owners for the same collectionId.
     */
    public subscribe(collectionId: number): void {
        const existing = this.connections.get(collectionId);
        if (existing) {
            existing.refCount++;
            return;
        }

        this.connections.set(collectionId, {
            eventSource: null,
            reconnectTimeout: null,
            reconnectAttempts: 0,
            manualDisconnect: false,
            refCount: 1,
        });
        this.clearProgress(collectionId);
        this.connect(collectionId);
    }

    /**
     * Releases one owner's interest in a collection's indexing stream. Decrements the
     * refCount; only closes the EventSource once it reaches 0. A no-op if this
     * collectionId has no active connection (e.g. it already reached a terminal status).
     */
    public unsubscribe(collectionId: number): void {
        const connection = this.connections.get(collectionId);
        if (!connection) return;

        connection.refCount--;
        if (connection.refCount > 0) return;

        this.closeConnection(collectionId, connection);
    }

    private connect(collectionId: number): void {
        const connection = this.connections.get(collectionId);
        if (!connection) return;

        this.sseTicketService.fetchTicket().subscribe({
            next: (ticket) => this.openEventSource(collectionId, ticket),
            error: (err: unknown) => {
                console.error(`Failed to fetch SSE ticket for collection ${collectionId} indexing:`, err);
                this.handleConnectionLoss(collectionId);
            },
        });
    }

    private openEventSource(collectionId: number, ticket: string): void {
        const connection = this.connections.get(collectionId);
        if (!connection || connection.manualDisconnect) return;

        if (connection.eventSource) {
            console.warn(`Indexing SSE already open for collection ${collectionId}`);
            return;
        }

        const url = `${this.configService.apiUrl}source-collections/subscribe/${collectionId}/?ticket=${encodeURIComponent(ticket)}`;
        const eventSource = new EventSource(url);
        connection.eventSource = eventSource;

        eventSource.onopen = () => {
            connection.reconnectAttempts = 0;
        };

        eventSource.addEventListener('indexing', (event: MessageEvent) => {
            const parsedEvent = this.parseIndexingEvent(event.data);
            if (!parsedEvent) {
                console.warn('Received malformed indexing SSE payload:', event.data);
                return;
            }
            this.applyIndexingEvent(parsedEvent);
        });

        eventSource.onerror = (err) => {
            console.error(`Indexing SSE error for collection ${collectionId}:`, err);
            this.teardownEventSource(connection);
            this.handleConnectionLoss(collectionId);
        };
    }

    private applyIndexingEvent(event: CollectionIndexingEventDto): void {
        this.progressSignal.update((map) => {
            const next = new Map(map);
            next.set(event.collection_id, {
                done: event.done,
                total: event.total,
                collectionStatus: event.collection_status,
                currentDocumentConfigId: event.document_config_id,
                currentDocumentStatus: event.doc_status,
                error: event.error,
            });
            return next;
        });

        this.collectionsStorageService.updateCollectionStatus(event.collection_id, event.collection_status);

        if (TERMINAL_COLLECTION_STATUSES.has(event.collection_status)) {
            // Terminal status: the stream is done. Force-close regardless of how many
            // owners still hold a ref — their later unsubscribe() calls become no-ops.
            const connection = this.connections.get(event.collection_id);
            if (connection) {
                this.closeConnection(event.collection_id, connection);
            }
        }
    }

    private handleConnectionLoss(collectionId: number): void {
        const connection = this.connections.get(collectionId);
        if (!connection || connection.manualDisconnect) return;

        if (connection.reconnectAttempts >= MAX_RECONNECT_ATTEMPTS) {
            console.error(
                `Max SSE reconnect attempts (${MAX_RECONNECT_ATTEMPTS}) reached for collection ${collectionId}. Giving up.`
            );
            this.closeConnection(collectionId, connection);
            return;
        }

        connection.reconnectAttempts++;
        const delay = this.calculateReconnectDelay(connection.reconnectAttempts);

        connection.reconnectTimeout = setTimeout(() => {
            if (!connection.manualDisconnect && this.connections.has(collectionId)) {
                this.connect(collectionId);
            }
        }, delay);
    }

    private calculateReconnectDelay(attempt: number): number {
        // Exponential backoff with jitter to prevent thundering herd
        const exponentialDelay = BASE_RECONNECT_DELAY_MS * Math.pow(2, attempt - 1);
        const jitter = Math.random() * 0.1 * exponentialDelay;
        return Math.min(exponentialDelay + jitter, MAX_RECONNECT_DELAY_MS);
    }

    private teardownEventSource(connection: IndexingConnection): void {
        if (connection.eventSource) {
            connection.eventSource.close();
            connection.eventSource = null;
        }
    }

    private teardownConnection(connection: IndexingConnection): void {
        if (connection.reconnectTimeout) {
            clearTimeout(connection.reconnectTimeout);
            connection.reconnectTimeout = null;
        }
        this.teardownEventSource(connection);
    }

    /** Fully tears down and removes a connection, unconditionally (bypasses refCount). */
    private closeConnection(collectionId: number, connection: IndexingConnection): void {
        connection.manualDisconnect = true;
        this.teardownConnection(connection);
        this.connections.delete(collectionId);
    }

    private clearProgress(collectionId: number): void {
        this.progressSignal.update((map) => {
            if (!map.has(collectionId)) return map;
            const next = new Map(map);
            next.delete(collectionId);
            return next;
        });
    }

    private parseIndexingEvent(raw: string): CollectionIndexingEventDto | null {
        let data: unknown;
        try {
            data = JSON.parse(raw);
        } catch {
            return null;
        }

        if (typeof data !== 'object' || data === null) return null;
        const record = data as Record<string, unknown>;

        if (typeof record['collection_id'] !== 'number') return null;
        if (typeof record['rag_id'] !== 'number') return null;
        if (typeof record['rag_type'] !== 'string') return null;
        if (typeof record['done'] !== 'number') return null;
        if (typeof record['total'] !== 'number') return null;
        if (!this.isCollectionStatus(record['collection_status'])) return null;

        const documentConfigId = typeof record['document_config_id'] === 'number' ? record['document_config_id'] : null;
        const docStatus = typeof record['doc_status'] === 'string' ? record['doc_status'] : null;
        const error = typeof record['error'] === 'string' ? record['error'] : null;

        return {
            collection_id: record['collection_id'],
            rag_id: record['rag_id'],
            rag_type: record['rag_type'],
            document_config_id: documentConfigId,
            doc_status: docStatus,
            done: record['done'],
            total: record['total'],
            collection_status: record['collection_status'],
            error,
        };
    }

    private isCollectionStatus(value: unknown): value is CollectionStatus {
        if (typeof value !== 'string') return false;
        return (Object.values(CollectionStatus) as string[]).includes(value);
    }
}
