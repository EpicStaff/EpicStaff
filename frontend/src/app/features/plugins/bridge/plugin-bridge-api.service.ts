import { HttpClient, HttpContext, HttpParams } from '@angular/common/http';
import { inject, Injectable } from '@angular/core';
import { map, Observable } from 'rxjs';

import { SKIP_FORBIDDEN_RELOAD } from '../../../core/interceptors/skip-forbidden-reload.context';
import { ConfigService } from '../../../services/config';

/** `POST /api/run-session/` answer. */
export interface BridgeRunSessionResponse {
    session_id: number;
}

/**
 * The fields of `GET /api/sessions/{id}/` the bridge reads. `graph` is the flow's id
 * (`SessionSerializer` serializes the foreign key as its primary key).
 */
export interface BridgeSessionRecord {
    id: number;
    graph: number | null;
    status: string;
    variables: unknown;
}

/** The fields of one `GET /api/key-value-table-entries/` row the bridge reads: a preview, not the value. */
export interface BridgeKeyValueListItem {
    id: number;
    table: number;
    key: string;
    value_preview: string;
    value_truncated: boolean;
    created_at: string;
    updated_at: string;
}

/** `GET /api/key-value-table-entries/` (limit/offset pagination). */
export interface BridgeKeyValueListResponse {
    count: number;
    results: BridgeKeyValueListItem[];
}

/** The fields of `GET /api/key-value-table-entries/{id}/` the bridge reads. */
export interface BridgeKeyValueEntryRecord {
    id: number;
    table: number;
    key: string;
    value: unknown;
    created_at: string;
    updated_at: string;
}

export type BridgeKeyValueOrdering = 'key' | '-key' | 'updated_at' | '-updated_at';

export interface BridgeKeyValueListQuery {
    tableId: number;
    ordering: BridgeKeyValueOrdering;
    limit: number;
    offset: number;
    /** Sent only when not empty. */
    search: string;
}

/**
 * The HTTP calls the plugin bridge makes for a plugin page, as the signed-in user. HTTP only,
 * no state; access checks happen before any of these is called.
 *
 * Every request is marked {@link SKIP_FORBIDDEN_RELOAD}: a 403 here means the user's role lacks
 * the flow permission the plugin asked for, which the bridge answers with `forbidden`. Without
 * the mark, `forbiddenInterceptor` would treat it as stale permissions and remount the page.
 */
@Injectable({ providedIn: 'root' })
export class PluginBridgeApiService {
    private readonly http = inject(HttpClient);
    private readonly configService = inject(ConfigService);

    private get apiUrl(): string {
        return this.configService.apiUrl;
    }

    /** Starts a flow. Sends `variables` (not `initial_state`, which `RunGraphService` uses). */
    runSession(graphId: number, variables: Record<string, unknown>): Observable<BridgeRunSessionResponse> {
        return this.http.post<BridgeRunSessionResponse>(
            `${this.apiUrl}run-session/`,
            { graph_id: graphId, variables },
            { context: bridgeContext() }
        );
    }

    getSession(sessionId: number): Observable<BridgeSessionRecord> {
        return this.http.get<BridgeSessionRecord>(`${this.apiUrl}sessions/${sessionId}/`, {
            context: bridgeContext(),
        });
    }

    stopSession(sessionId: number): Observable<void> {
        return this.http.post<void>(`${this.apiUrl}sessions/${sessionId}/stop/`, {}, { context: bridgeContext() });
    }

    /** `GET /api/key-value-table-entries/?table=&ordering=&limit=&offset=[&search=]`, in that order. */
    listKeyValueEntries(query: BridgeKeyValueListQuery): Observable<BridgeKeyValueListResponse> {
        let params = new HttpParams()
            .set('table', query.tableId)
            .set('ordering', query.ordering)
            .set('limit', query.limit)
            .set('offset', query.offset);
        if (query.search !== '') params = params.set('search', query.search);
        return this.http.get<BridgeKeyValueListResponse>(`${this.apiUrl}key-value-table-entries/`, {
            params,
            context: bridgeContext(),
        });
    }

    /**
     * The id of the entry with exactly this key in this table, or `null`:
     * `GET /api/key-value-table-entries/?table=&key=&limit=1`. A returned row of another table or
     * key (a server without the exact `key` filter ignores it) counts as no entry.
     */
    findKeyValueEntryId(tableId: number, key: string): Observable<number | null> {
        const params = new HttpParams().set('table', tableId).set('key', key).set('limit', 1);
        return this.http
            .get<BridgeKeyValueListResponse>(`${this.apiUrl}key-value-table-entries/`, {
                params,
                context: bridgeContext(),
            })
            .pipe(
                map((response) => {
                    const entry = Array.isArray(response?.results) ? response.results[0] : undefined;
                    const matches = entry?.table === tableId && entry.key === key && Number.isSafeInteger(entry.id);
                    return matches ? entry.id : null;
                })
            );
    }

    getKeyValueEntry(entryId: number): Observable<BridgeKeyValueEntryRecord> {
        return this.http.get<BridgeKeyValueEntryRecord>(`${this.apiUrl}key-value-table-entries/${entryId}/`, {
            context: bridgeContext(),
        });
    }

    /** The run-session SSE stream URL for a single-use ticket from `SseTicketService`. */
    sessionStreamUrl(sessionId: number, ticket: string): string {
        return `${this.apiUrl}run-session/subscribe/${sessionId}/?ticket=${encodeURIComponent(ticket)}`;
    }
}

function bridgeContext(): HttpContext {
    return new HttpContext().set(SKIP_FORBIDDEN_RELOAD, true);
}
