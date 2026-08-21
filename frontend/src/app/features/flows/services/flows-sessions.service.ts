import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable } from '@angular/core';
import { map, Observable, Subject } from 'rxjs';

import { ApiGetRequest } from '../../../core/models/api-request.model';
import { GraphMessage } from '../../../pages/running-graph/models/graph-session-message.model';
import { WarningMessages } from '../../../pages/running-graph/models/warning-messages.model';
import { ConfigService } from '../../../services/config/config.service';
import { DateRangeFilter } from '../../../shared/models/date-range-filter.model';

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

export const TERMINAL_SESSION_STATUSES: ReadonlySet<GraphSessionStatus> = new Set([
    GraphSessionStatus.ENDED,
    GraphSessionStatus.ERROR,
    GraphSessionStatus.STOP,
    GraphSessionStatus.EXPIRED,
]);

export const isTerminalSessionStatus = (status: GraphSessionStatus): boolean => TERMINAL_SESSION_STATUSES.has(status);

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

export type TriggerType = 'manual' | 'schedule' | 'webhook' | 'telegram' | 'parent_flow';

export interface SessionTrigger {
    trigger_type: TriggerType | string;
    trigger_id: number | null;
}

export interface GraphSessionLight {
    id: number;
    graph_id: number;
    graph_name: string;
    status: GraphSessionStatus;
    status_updated_at: string;
    created_at: string;
    finished_at: string | null;
    trigger: SessionTrigger | null;
}

export interface DurationFilter {
    operator: DurationOperator;
    value: number;
    value2?: number;
}

export type DurationOperator = 'lessThan' | 'greaterThan' | 'equal' | 'between';

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
        status?: string[],
        nodeName?: string | null
    ): Observable<ApiGetRequest<GraphSession>>;

    getSessionsByGraphId(
        graphId: number,
        detailed: false,
        limit?: number,
        offset?: number,
        status?: string[],
        nodeName?: string | null,
        isErrorCause?: boolean,
        durationFilter?: DurationFilter | null,
        triggerType?: TriggerType[],
        dateFilter?: DateRangeFilter | null
    ): Observable<ApiGetRequest<GraphSessionLight>>;

    getSessionsByGraphId(
        graphId: number,
        detailed?: boolean,
        limit?: number,
        offset?: number,
        status?: string[],
        nodeName?: string | null,
        isErrorCause?: boolean,
        durationFilter?: DurationFilter | null,
        triggerType?: TriggerType[],
        dateFilter?: DateRangeFilter | null
    ): Observable<ApiGetRequest<GraphSession | GraphSessionLight>> {
        let params = new HttpParams().set('graph_id', graphId.toString());

        if (detailed !== undefined) params = params.set('detailed', detailed.toString());
        if (limit !== undefined) params = params.set('limit', limit.toString());
        if (offset !== undefined) params = params.set('offset', offset.toString());
        if (status !== undefined && !status.includes('all')) params = params.set('status', status.join(','));
        if (nodeName) params = params.set('node_name', nodeName);
        if (isErrorCause) params = params.set('is_error_cause', 'true');
        if (durationFilter) params = this.applyDurationParams(params, durationFilter);
        if (triggerType && triggerType.length > 0) params = params.set('trigger_type', triggerType.join(','));
        if (dateFilter) params = this.applyDateParams(params, dateFilter);
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

    getSessionMessages(
        sessionId: number | string,
        limit: number,
        offset: number,
        parentSubgraphExecutionId?: string
    ): Observable<ApiGetRequest<GraphMessage>> {
        let params = new HttpParams()
            .set('session_id', sessionId.toString())
            .set('limit', limit.toString())
            .set('offset', offset.toString());
        if (parentSubgraphExecutionId) {
            params = params.set('parent_subgraph_execution_id', parentSubgraphExecutionId);
        }
        return this.http.get<ApiGetRequest<GraphMessage>>(this.configService.apiUrl + 'graph-session-messages/', {
            params,
        });
    }

    getGlobalSessions(
        limit?: number,
        offset?: number,
        status?: string[],
        ordering?: string,
        graphName?: string[],
        triggerType?: TriggerType[],
        isErrorCause?: boolean,
        durationFilter?: DurationFilter | null,
        dateFilter?: DateRangeFilter | null
    ): Observable<ApiGetRequest<GraphSessionLight>> {
        let params = new HttpParams();
        params = params.set('detailed', 'false');
        if (limit !== undefined) params = params.set('limit', limit.toString());
        if (offset !== undefined) params = params.set('offset', offset.toString());
        if (status && !status.includes('all')) params = params.set('status', status.join(','));
        if (ordering) params = params.set('ordering', ordering);
        if (graphName && graphName.length > 0) params = params.set('graph_name', graphName.join(','));
        if (triggerType && triggerType.length > 0) params = params.set('trigger_type', triggerType.join(','));
        if (isErrorCause) params = params.set('is_error_cause', 'true');
        if (durationFilter) params = this.applyDurationParams(params, durationFilter);
        if (dateFilter) params = this.applyDateParams(params, dateFilter);

        return this.http.get<ApiGetRequest<GraphSessionLight>>(this.apiUrl, { params });
    }

    private applyDateParams(params: HttpParams, filter: DateRangeFilter): HttpParams {
        if (filter.after) params = params.set('created_at_after', filter.after);
        if (filter.before) params = params.set('created_at_before', filter.before);
        return params;
    }

    private applyDurationParams(params: HttpParams, filter: DurationFilter): HttpParams {
        if (filter.operator === 'lessThan') return params.set('duration_lt', filter.value.toString());
        if (filter.operator === 'greaterThan') return params.set('duration_gt', filter.value.toString());
        if (filter.operator === 'equal') {
            params = params.set('duration_gte', filter.value.toString());
            params = params.set('duration_lte', filter.value.toString());
        }
        if (filter.operator === 'between') {
            params = params.set('duration_gte', filter.value.toString());
            if (filter.value2 != null) params = params.set('duration_lte', filter.value2.toString());
        }
        return params;
    }
}
