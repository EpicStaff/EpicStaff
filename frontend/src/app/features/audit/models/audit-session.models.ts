export type AuditEventKind = 'session' | 'node' | 'event';
export type AuditEventStatus = 'completed' | 'failed';
export type AuditSessionRowStatus = AuditEventStatus | 'running';

export const AUDIT_MESSAGE_TYPE = {
    sessionStart: 'session_start',
    sessionEnd: 'session_end',
};

export interface AuditSessionEvent {
    id: string;
    parent_id: string;
    session_id: number;
    session_message_id: string | null;
    kind: AuditEventKind;
    status: AuditEventStatus | null;
    name: string;
    flow_name: string;
    node_type: string;
    run_type: string;
    input: Record<string, unknown> | null;
    output: Record<string, unknown> | null;
    error: string | null;
    details: Record<string, unknown>;
    event_time: string;
    record_time: string | null;
    ord_id: number;
}

export interface AuditMatchScope {
    full_session_history?: boolean;
    ancestors?: boolean;
    children?: boolean;
    rows_before?: number;
}

export interface SessionSearchRequest {
    query?: string;
    filters?: unknown;
    match_scope?: AuditMatchScope;
    cursor?: string | null;
    size: number;
}

export interface SessionSearchResponse {
    items: AuditSessionEvent[];
    next_cursor: string | null;
    partial: boolean;
}

export interface AuditSessionRow {
    sessionId: number;
    identityId: string;
    name: string;
    flowName: string;
    runType: string;
    status: AuditSessionRowStatus;
    startTime: string | null;
    endTime: string | null;
    durationMs: number | null;
    output: Record<string, unknown> | null;
    error: string | null;
    details: Record<string, unknown> | null;
    children: AuditSessionEvent[];
}
