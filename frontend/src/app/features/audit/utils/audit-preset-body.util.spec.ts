import {
    AuditFilterState,
    createAuditCondition,
    createAuditConditionGroup,
    DEFAULT_MATCH_SCOPE,
    EMPTY_AUDIT_FILTER,
} from '../models/audit-filter.models';
import { SESSION_FIELD_CATALOG } from '../models/audit-filter-options';
import { USER_ACTION_FIELD_CATALOG } from '../models/audit-user-action-filter-options';
import { buildPresetBody, restorePresetState } from './audit-preset-body.util';
import { compileAuditFilter } from './compile-audit-filter.util';

describe('audit preset body', () => {
    it('stores the same search as compileAuditFilter plus the panel state', () => {
        const state: AuditFilterState = { ...EMPTY_AUDIT_FILTER, kinds: ['event'] };
        const body = buildPresetBody(state, SESSION_FIELD_CATALOG);
        const compiled = compileAuditFilter(state, SESSION_FIELD_CATALOG);

        expect(body.filters).toEqual(compiled.filters);
        expect(body.query).toBeUndefined();
        expect(body.match_scope).toEqual(compiled.matchScope);
        expect(body.ui_state?.state).toEqual(state);
    });

    it('stores a query-mode search as a query, not as filters', () => {
        const body = buildPresetBody(
            { ...EMPTY_AUDIT_FILTER, mode: 'query', query: 'status in ["failed"]' },
            SESSION_FIELD_CATALOG
        );

        expect(body.query).toBe('status in ["failed"]');
        expect(body.filters).toBeUndefined();
    });

    it('round-trips a saved state unchanged', () => {
        const state: AuditFilterState = { ...EMPTY_AUDIT_FILTER, mode: 'query', query: 'status in ["failed"]' };

        expect(restorePresetState(buildPresetBody(state, SESSION_FIELD_CATALOG), SESSION_FIELD_CATALOG)).toEqual(state);
    });

    it('fills fields a preset saved before they existed', () => {
        const { matchScope, query, mode, ...olderState } = EMPTY_AUDIT_FILTER;
        const restored = restorePresetState(
            {
                ui_state: { version: 1, state: { ...olderState, kinds: ['node'] } as AuditFilterState },
            },
            SESSION_FIELD_CATALOG
        );

        expect(restored?.kinds).toEqual(['node']);
        expect(restored?.query).toBe(query);
        expect(restored?.mode).toBe(mode);
        expect(restored?.matchScope).toEqual(matchScope);
    });

    it('fills match scope fields a preset saved before they existed', () => {
        const restored = restorePresetState(
            {
                ui_state: {
                    version: 1,
                    state: { ...EMPTY_AUDIT_FILTER, matchScope: { children: true } } as AuditFilterState,
                },
            },
            SESSION_FIELD_CATALOG
        );

        expect(restored?.matchScope).toEqual({ ...EMPTY_AUDIT_FILTER.matchScope, children: true });
    });

    it('opens a preset created with only a query as a query', () => {
        expect(restorePresetState({ query: 'name == "Session Start"' }, SESSION_FIELD_CATALOG)).toEqual({
            ...EMPTY_AUDIT_FILTER,
            mode: 'query',
            query: 'name == "Session Start"',
        });
    });

    it('restores the match scope of a preset created with only a query', () => {
        const restored = restorePresetState(
            {
                query: 'name == "Session Start"',
                match_scope: { children: true, rows_before: 5 },
            },
            SESSION_FIELD_CATALOG
        );

        expect(restored?.matchScope).toEqual({
            ...DEFAULT_MATCH_SCOPE,
            children: true,
            rowsBeforeEnabled: true,
            rowsBefore: 5,
        });
    });

    it('keeps the default match scope for a query-only preset without one', () => {
        expect(restorePresetState({ query: 'name == "Session Start"' }, SESSION_FIELD_CATALOG)?.matchScope).toEqual(
            DEFAULT_MATCH_SCOPE
        );
    });

    it('cannot restore a preset created with only raw filters', () => {
        expect(
            restorePresetState({ filters: { field: 'kind', op: 'in', value: ['event'] } }, SESSION_FIELD_CATALOG)
        ).toBeNull();
    });
});

describe('user actions preset body', () => {
    it('stores the search without a match scope, which only sessions accept', () => {
        const state: AuditFilterState = {
            ...EMPTY_AUDIT_FILTER,
            selections: { action: { op: 'in', values: ['deleted'] } },
        };

        const body = buildPresetBody(state, USER_ACTION_FIELD_CATALOG);

        expect(body).toEqual({
            filters: { field: 'action', op: 'in', value: ['deleted'] },
            ui_state: { version: 1, state },
        });
    });

    it('restores the picked flows and members a preset was saved with', () => {
        const state: AuditFilterState = {
            ...EMPTY_AUDIT_FILTER,
            selections: {
                actor_user_id: { op: 'not_in', values: ['7'] },
                flow_id: { op: 'in', values: ['12', '15'] },
            },
        };

        const restored = restorePresetState(
            buildPresetBody(state, USER_ACTION_FIELD_CATALOG),
            USER_ACTION_FIELD_CATALOG
        );

        expect(restored?.selections).toEqual(state.selections);
    });

    it('drops the fields of a preset saved before the Builder stopped offering them', () => {
        const typed = (value: string) => [
            { ...createAuditConditionGroup(), conditions: [{ ...createAuditCondition(), value }] },
        ];
        const restored = restorePresetState(
            {
                ui_state: {
                    version: 1,
                    state: {
                        ...EMPTY_AUDIT_FILTER,
                        selections: { action: { op: 'in', values: ['deleted'] } },
                        textConditions: {
                            actor_email: typed('ann'),
                            parent_type: typed('flow'),
                            parent_name: typed('Billing'),
                            target_name: typed('Invoice'),
                        },
                    },
                },
            },
            USER_ACTION_FIELD_CATALOG
        );

        expect(restored?.selections).toEqual({ action: { op: 'in', values: ['deleted'] } });
        expect(Object.keys(restored?.textConditions ?? {})).toEqual(['target_name']);
    });
});
