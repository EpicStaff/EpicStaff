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
export interface AuditPreset {
    id: number;
    name: string;
    filter_body: AuditPresetBody;
    created_at: string;
    updated_at: string;
}
