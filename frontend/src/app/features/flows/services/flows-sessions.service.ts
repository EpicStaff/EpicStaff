import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable } from '@angular/core';
import { map, Observable, Subject } from 'rxjs';

import { ApiGetRequest } from '../../../core/models/api-request.model';
import { WarningMessages } from '../../../pages/running-graph/models/warning-messages.model';
import { ConfigService } from '../../../services/config/config.service';

export interface GraphSessionGraph {
    id: number;
    name: string;
    metadata: Record<string, unknown>;
}

export enum GraphSessionStatus {
    RUNNING = 'run',
    ERROR = 'error',
    ENDED = 'end',
    WAITING_FOR_USER = 'wait_for_user',
    PENDING = 'pending',
    EXPIRED = 'expired',
    STOP = 'stop',
}

export interface GraphSession {
    id: number;
    graph: GraphSessionGraph;
    status: GraphSessionStatus;
    status_data: Record<string, unknown>;
    initial_state: Record<string, unknown>;
    created_at: string;
    finished_at: string | null;
}

export interface SessionUpdates {
    status: GraphSessionStatus;
}

export interface GraphSessionLight {
    id: number;
    graph_id: number;
    status: GraphSessionStatus;
    status_updated_at: string;
    created_at: string;
    finished_at: string | null;
}

export type SessionStatusesCounts = {
    run: number;
    wait_for_user: number;
    error: number;
    pending: number;
    stop: number;
};

export type GraphSessionStatusesCounts = {
    [graph_id: string]: SessionStatusesCounts;
};

export type SessionStatusesCountsMap = Map<string, SessionStatusesCounts>;

export const defaultSessionStatusesCounts = (): SessionStatusesCounts => ({
    run: 0,
    wait_for_user: 0,
    error: 0,
    pending: 0,
    stop: 0,
});

@Injectable({
    providedIn: 'root',
})
export class GraphSessionService {
    private readonly _sessionsChanged$ = new Subject<void>();
    public readonly sessionsChanged$ = this._sessionsChanged$.asObservable();

    constructor(
        private http: HttpClient,
        private configService: ConfigService
    ) {}

    private get apiUrl(): string {
        return this.configService.apiUrl + 'sessions/';
    }

    getAllSessions(): Observable<GraphSession[]> {
        return this.http.get<ApiGetRequest<GraphSession>>(this.apiUrl).pipe(
            map((response) => {
                return response.results.sort((a, b) => b.id - a.id);
            })
        );
    }

    getSessionStatuses(graphId?: string): Observable<SessionStatusesCountsMap> {
        const params = new HttpParams().set('graph_id', graphId!.toString());
        return this.http.get<GraphSessionStatusesCounts>(this.apiUrl + 'statuses/', { params }).pipe(
            map((response) => {
                const outerMap: SessionStatusesCountsMap = new Map();
                Object.entries(response).forEach(([graphId, statuses]) => {
                    const normalizedStatuses: SessionStatusesCounts = {
                        ...defaultSessionStatusesCounts(),
                        ...statuses,
                    };
                    outerMap.set(graphId, normalizedStatuses);
                });
                return outerMap;
            })
        );
    }

    getSessionById(sessionId: number): Observable<GraphSession> {
        return this.http.get<GraphSession>(`${this.apiUrl}${sessionId}/`);
    }

    getSessionUpdates(sessionId: string): Observable<SessionUpdates> {
        return this.http.get<SessionUpdates>(`${this.apiUrl}${sessionId}/get-updates/`);
    }

    getSessionsByGraphId(
        graphId: number,
        detailed: true,
        limit?: number,
        offset?: number,
        status?: string[]
    ): Observable<ApiGetRequest<GraphSession>>;

    getSessionsByGraphId(
        graphId: number,
        detailed: false,
        limit?: number,
        offset?: number,
        status?: string[]
    ): Observable<ApiGetRequest<GraphSessionLight>>;

    getSessionsByGraphId(
        graphId: number,
        detailed?: boolean,
        limit?: number,
        offset?: number,
        status?: string[]
    ): Observable<ApiGetRequest<GraphSession | GraphSessionLight>> {
        let params = new HttpParams().set('graph_id', graphId.toString());

        if (detailed !== undefined) params = params.set('detailed', detailed.toString());
        if (limit !== undefined) params = params.set('limit', limit.toString());
        if (offset !== undefined) params = params.set('offset', offset.toString());
        if (status !== undefined && !status.includes('all')) params = params.set('status', status.join(','));

        if (detailed === false) {
            return this.http.get<ApiGetRequest<GraphSessionLight>>(this.apiUrl, {
                params,
            });
        } else {
            return this.http.get<ApiGetRequest<GraphSession>>(this.apiUrl, {
                params,
            });
        }
    }

    deleteSessionById(sessionId: number): Observable<void> {
        return this.http.delete<void>(`${this.apiUrl}${sessionId}/`).pipe(
            map(() => {
                this._sessionsChanged$.next();
            })
        );
    }

    bulkDeleteSessions(ids: number[]): Observable<void> {
        return this.http.post<void>(`${this.apiUrl}bulk_delete/`, { ids }).pipe(
            map(() => {
                this._sessionsChanged$.next();
            })
        );
    }

    stopSessionById(sessionId: number): Observable<void> {
        return this.http.post<void>(`${this.apiUrl}${sessionId}/stop/`, {});
    }

    getSessionWarnings(sessionId: string): Observable<WarningMessages> {
        return this.http.get<WarningMessages>(`${this.apiUrl}${sessionId}/warnings/`);
    }
}
