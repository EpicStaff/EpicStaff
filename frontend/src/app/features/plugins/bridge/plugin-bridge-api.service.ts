import { HttpClient, HttpContext } from '@angular/common/http';
import { inject, Injectable } from '@angular/core';
import { Observable } from 'rxjs';

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

    /** The run-session SSE stream URL for a single-use ticket from `SseTicketService`. */
    sessionStreamUrl(sessionId: number, ticket: string): string {
        return `${this.apiUrl}run-session/subscribe/${sessionId}/?ticket=${encodeURIComponent(ticket)}`;
    }
}

function bridgeContext(): HttpContext {
    return new HttpContext().set(SKIP_FORBIDDEN_RELOAD, true);
}
