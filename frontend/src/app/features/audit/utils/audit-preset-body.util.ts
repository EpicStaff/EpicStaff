import { AuditCatalogField, AuditFieldCatalog } from '../models/audit-domain.models';
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

// The body is the domain's search request, so only a sessions preset carries a match scope.
export function buildPresetBody(state: AuditFilterState, catalog: AuditFieldCatalog): AuditPresetBody {
    const { filters, query, matchScope } = compileAuditFilter(state, catalog);
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

// Keeps only the entries the catalog's Builder still offers in that shape, so a field removed or turned from
// typed conditions into a picked list is dropped instead of lingering unseen in the state.
function keepCatalogFields(state: AuditFilterState, catalog: AuditFieldCatalog): AuditFilterState {
    const keep = <T>(
        values: Record<string, T> | undefined,
        kinds: AuditCatalogField['kind'][]
    ): Record<string, T> | undefined => {
        if (!values) {
            return undefined;
        }
        const offered = catalog.builderFields.filter((item) => kinds.includes(item.kind));
        return Object.fromEntries(
            Object.entries(values).filter(([field]) => offered.some((item) => item.field === field))
        );
    };
    return {
        ...state,
        selections: keep(state.selections, ['select', 'lookup']),
        textConditions: keep(state.textConditions, ['text']),
        idFilters: keep(state.idFilters, ['id']),
    };
}

export function restorePresetState(body: AuditPresetBody, catalog: AuditFieldCatalog): AuditFilterState | null {
    const saved = body.ui_state?.state;
    if (saved) {
        return keepCatalogFields(mergeSavedFilterState(saved), catalog);
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
