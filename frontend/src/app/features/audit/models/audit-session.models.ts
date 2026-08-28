export type AuditEventKind = 'session' | 'node' | 'event';
export type AuditEventStatus = 'completed' | 'failed';

export interface AuditSessionEvent {
    id: string;
    parent_id: string;
    session_id: number;
    session_message_id: string | null;
    kind: AuditEventKind;
    status: AuditEventStatus;
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
