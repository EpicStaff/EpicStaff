import { AuditFilterNode, AuditFilterState } from './audit-filter.models';
import { AuditMatchScope } from './audit-session.models';

export interface AuditPresetUiState {
    version: number;
    state: AuditFilterState;
}

export interface AuditPresetBody {
    filters?: AuditFilterNode;
    query?: string;
    match_scope?: AuditMatchScope;
    ui_state?: AuditPresetUiState;
}

export type AuditPresetScope = 'mine' | 'shared';

// Only the author may PATCH; sharing is one-way, so is_shared is only ever sent as true.
export interface AuditPresetChanges {
    name?: string;
    filter_body?: AuditPresetBody;
    is_shared?: true;
}

export interface AuditPreset {
    id: number;
    name: string;
    filter_body: AuditPresetBody;
    is_owner: boolean;
    is_shared: boolean;
    created_by_name: string;
    created_at: string;
    updated_at: string;
}
