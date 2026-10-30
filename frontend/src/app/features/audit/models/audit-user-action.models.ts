import { AuditFilterNode } from './audit-filter.models';

export interface AuditUserAction {
    id: string;
    org_id: number;
    event_time: string;
    record_time: string | null;
    filter_matched: boolean;
    actor_user_id: number | null;
    actor_email: string;
    actor_api_key_name: string | null;
    action: string;
    target_type: string | null;
    target_id: string | null;
    target_name: string | null;
    previous_name: string | null;
    parent_type: string | null;
    parent_id: string | null;
    parent_name: string | null;
    route: string | null;
}

export interface UserActionSearchRequest {
    filters?: AuditFilterNode;
    query?: string;
    cursor?: string | null;
    size?: number;
}

export interface UserActionSearchResponse {
    items: AuditUserAction[];
    next_cursor: string | null;
    partial: boolean;
}
