import { AuditFilterState, DEFAULT_MATCH_SCOPE, EMPTY_AUDIT_FILTER } from '../models/audit-filter.models';
import { buildPresetBody, restorePresetState } from './audit-preset-body.util';
import { compileAuditFilter } from './compile-audit-filter.util';

describe('audit preset body', () => {
    it('stores the same search as compileAuditFilter plus the panel state', () => {
        const state: AuditFilterState = { ...EMPTY_AUDIT_FILTER, kinds: ['event'] };
        const body = buildPresetBody(state);
        const compiled = compileAuditFilter(state);

        expect(body.filters).toEqual(compiled.filters);
        expect(body.query).toBeUndefined();
        expect(body.match_scope).toEqual(compiled.matchScope);
        expect(body.ui_state?.state).toEqual(state);
    });

    it('stores a query-mode search as a query, not as filters', () => {
        const body = buildPresetBody({ ...EMPTY_AUDIT_FILTER, mode: 'query', query: 'status in ["failed"]' });

        expect(body.query).toBe('status in ["failed"]');
        expect(body.filters).toBeUndefined();
    });

    it('round-trips a saved state unchanged', () => {
        const state: AuditFilterState = { ...EMPTY_AUDIT_FILTER, mode: 'query', query: 'status in ["failed"]' };

        expect(restorePresetState(buildPresetBody(state))).toEqual(state);
    });

    it('fills fields a preset saved before they existed', () => {
        const { matchScope, query, mode, ...olderState } = EMPTY_AUDIT_FILTER;
        const restored = restorePresetState({
            ui_state: { version: 1, state: { ...olderState, kinds: ['node'] } as AuditFilterState },
        });

        expect(restored?.kinds).toEqual(['node']);
        expect(restored?.query).toBe(query);
        expect(restored?.mode).toBe(mode);
        expect(restored?.matchScope).toEqual(matchScope);
    });

    it('fills match scope fields a preset saved before they existed', () => {
        const restored = restorePresetState({
            ui_state: {
                version: 1,
                state: { ...EMPTY_AUDIT_FILTER, matchScope: { children: true } } as AuditFilterState,
            },
        });

        expect(restored?.matchScope).toEqual({ ...EMPTY_AUDIT_FILTER.matchScope, children: true });
    });

    it('opens a preset created with only a query as a query', () => {
        expect(restorePresetState({ query: 'name == "Session Start"' })).toEqual({
            ...EMPTY_AUDIT_FILTER,
            mode: 'query',
            query: 'name == "Session Start"',
        });
    });

    it('restores the match scope of a preset created with only a query', () => {
        const restored = restorePresetState({
            query: 'name == "Session Start"',
            match_scope: { children: true, rows_before: 5 },
        });

        expect(restored?.matchScope).toEqual({
            ...DEFAULT_MATCH_SCOPE,
            children: true,
            rowsBeforeEnabled: true,
            rowsBefore: 5,
        });
    });

    it('keeps the default match scope for a query-only preset without one', () => {
        expect(restorePresetState({ query: 'name == "Session Start"' })?.matchScope).toEqual(DEFAULT_MATCH_SCOPE);
    });

    it('cannot restore a preset created with only raw filters', () => {
        expect(restorePresetState({ filters: { field: 'kind', op: 'in', value: ['event'] } })).toBeNull();
    });
});
