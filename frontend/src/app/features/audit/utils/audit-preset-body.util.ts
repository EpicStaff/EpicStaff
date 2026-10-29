import {
    AuditFilterState,
    AuditMatchScopeState,
    DEFAULT_MATCH_SCOPE,
    EMPTY_AUDIT_FILTER,
    MAX_ROWS_BEFORE,
} from '../models/audit-filter.models';
import { AuditPresetBody } from '../models/audit-preset.models';
import { AuditMatchScope } from '../models/audit-session.models';
import { compileAuditFilter } from './compile-audit-filter.util';

export const AUDIT_PRESET_UI_STATE_VERSION = 1;

export function buildPresetBody(state: AuditFilterState): AuditPresetBody {
    const { filters, query, matchScope } = compileAuditFilter(state);
    return {
        filters,
        query,
        match_scope: matchScope,
        ui_state: { version: AUDIT_PRESET_UI_STATE_VERSION, state },
    };
}

export function mergeSavedFilterState(saved: Partial<AuditFilterState>): AuditFilterState {
    return {
        ...EMPTY_AUDIT_FILTER,
        ...saved,
        matchScope: { ...DEFAULT_MATCH_SCOPE, ...saved.matchScope },
    };
}

export function restorePresetState(body: AuditPresetBody): AuditFilterState | null {
    const saved = body.ui_state?.state;
    if (saved) {
        return mergeSavedFilterState(saved);
    }
    if (typeof body.query === 'string') {
        return {
            ...EMPTY_AUDIT_FILTER,
            mode: 'query',
            query: body.query,
            matchScope: restoreMatchScope(body.match_scope),
        };
    }
    return null;
}

function restoreMatchScope(scope: AuditMatchScope | undefined): AuditMatchScopeState {
    const rowsBefore = Math.trunc(scope?.rows_before ?? 0);
    const rowsBeforeEnabled = rowsBefore > 0;
    return {
        children: scope?.children ?? DEFAULT_MATCH_SCOPE.children,
        rowsBeforeEnabled,
        rowsBefore: rowsBeforeEnabled ? Math.min(rowsBefore, MAX_ROWS_BEFORE) : DEFAULT_MATCH_SCOPE.rowsBefore,
        fullSessionHistory: scope?.full_session_history ?? DEFAULT_MATCH_SCOPE.fullSessionHistory,
    };
}
