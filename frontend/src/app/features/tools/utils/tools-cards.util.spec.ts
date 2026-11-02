import { AuditCondition, AuditConditionGroup } from '../../audit/models/audit-filter.models';
import { EMPTY_TOOLS_FILTER, ToolsFilterState } from '../models/tool-filter.model';
import {
    evaluateConditionGroups,
    matchesToolFilter,
    ToolFieldMap,
    ToolFilterAdapter,
    ToolFilterContext,
} from './tools-cards.util';

function condition(overrides: Partial<AuditCondition> = {}): AuditCondition {
    return { id: '1', join: 'and', key: '', op: 'contains', value: '', ...overrides };
}

function group(conditions: AuditCondition[], join: 'and' | 'or' = 'or'): AuditConditionGroup {
    return { id: 'g1', join, conditions };
}

describe('evaluateConditionGroups', () => {
    it('returns true when no groups have usable conditions', () => {
        const groups = [group([condition({ value: '' })])];
        expect(evaluateConditionGroups(groups, ['anything'])).toBe(true);
    });

    it('matches "contains" against searchable texts', () => {
        const groups = [group([condition({ op: 'contains', value: 'hello' })])];
        expect(evaluateConditionGroups(groups, ['say hello world'])).toBe(true);
        expect(evaluateConditionGroups(groups, ['goodbye'])).toBe(false);
    });

    it('matches "equals" case-insensitively', () => {
        const groups = [group([condition({ op: 'equals', value: 'Hello' })])];
        expect(evaluateConditionGroups(groups, ['hello'])).toBe(true);
        expect(evaluateConditionGroups(groups, ['hello world'])).toBe(false);
    });

    it('matches "not_equal"', () => {
        const groups = [group([condition({ op: 'not_equal', value: 'hello' })])];
        expect(evaluateConditionGroups(groups, ['hello'])).toBe(false);
        expect(evaluateConditionGroups(groups, ['world'])).toBe(true);
    });

    it('matches "not_contains"', () => {
        const groups = [group([condition({ op: 'not_contains', value: 'hello' })])];
        expect(evaluateConditionGroups(groups, ['say hello'])).toBe(false);
        expect(evaluateConditionGroups(groups, ['goodbye'])).toBe(true);
    });

    it('matches "starts_with"', () => {
        const groups = [group([condition({ op: 'starts_with', value: 'hel' })])];
        expect(evaluateConditionGroups(groups, ['hello'])).toBe(true);
        expect(evaluateConditionGroups(groups, ['say hello'])).toBe(false);
    });

    it('matches "ends_with"', () => {
        const groups = [group([condition({ op: 'ends_with', value: 'llo' })])];
        expect(evaluateConditionGroups(groups, ['hello'])).toBe(true);
        expect(evaluateConditionGroups(groups, ['hello!'])).toBe(false);
    });

    it('matches "is_empty"', () => {
        const groups = [group([condition({ op: 'is_empty', value: '' })])];
        expect(evaluateConditionGroups(groups, [''])).toBe(true);
        expect(evaluateConditionGroups(groups, ['not empty'])).toBe(false);
    });

    it('matches "is_not_empty"', () => {
        const groups = [group([condition({ op: 'is_not_empty', value: '' })])];
        expect(evaluateConditionGroups(groups, ['something'])).toBe(true);
        expect(evaluateConditionGroups(groups, [''])).toBe(false);
    });

    it('AND-joins conditions within a group', () => {
        const groups = [
            group([
                condition({ op: 'contains', value: 'foo', join: 'and' }),
                condition({ op: 'contains', value: 'bar', join: 'and' }),
            ]),
        ];
        expect(evaluateConditionGroups(groups, ['foo bar baz'])).toBe(true);
        expect(evaluateConditionGroups(groups, ['foo only'])).toBe(false);
    });

    it('OR-joins conditions within a group', () => {
        const groups = [
            group([
                condition({ op: 'contains', value: 'foo', join: 'or' }),
                condition({ op: 'contains', value: 'bar', join: 'or' }),
            ]),
        ];
        expect(evaluateConditionGroups(groups, ['just foo'])).toBe(true);
        expect(evaluateConditionGroups(groups, ['just bar'])).toBe(true);
        expect(evaluateConditionGroups(groups, ['nothing'])).toBe(false);
    });

    it('OR-joins multiple groups (at least one must match)', () => {
        const groups = [
            group([condition({ op: 'equals', value: 'alpha' })]),
            group([condition({ op: 'equals', value: 'beta' })]),
        ];
        expect(evaluateConditionGroups(groups, ['alpha'])).toBe(true);
        expect(evaluateConditionGroups(groups, ['beta'])).toBe(true);
        expect(evaluateConditionGroups(groups, ['gamma'])).toBe(false);
    });

    it('matches against any text in the array', () => {
        const groups = [group([condition({ op: 'equals', value: 'target' })])];
        expect(evaluateConditionGroups(groups, ['miss', 'target'])).toBe(true);
        expect(evaluateConditionGroups(groups, ['miss', 'also miss'])).toBe(false);
    });

    it('treats unsupported operators as matching', () => {
        // 'in' is not handled by matchesOperator, should default to true
        const groups = [group([condition({ op: 'in', value: 'x' })])];
        expect(evaluateConditionGroups(groups, ['anything'])).toBe(true);
    });
});

describe('matchesToolFilter — customConditions integration', () => {
    const adapter: ToolFilterAdapter<{ id: number; name: string }> = {
        idOf: (t) => t.id,
        nameOf: (t) => t.name,
        labelIdsOf: () => [],
        favoriteOf: () => false,
        searchableTextOf: (t) => [t.name],
        updatedAtOf: () => null,
    };

    function context(filter: Partial<ToolsFilterState> = {}): ToolFilterContext {
        return {
            filter: { ...EMPTY_TOOLS_FILTER, ...filter },
            sidebarLabelFilter: 'all',
            labelById: new Map(),
            searchTerm: '',
            usage: new Map(),
            applySourceFilter: false,
        };
    }

    it('passes when customConditions are empty (default state)', () => {
        const result = matchesToolFilter({ id: 1, name: 'My Tool' }, context(), adapter);
        expect(result).toBe(true);
    });

    it('filters by customConditions with a contains match', () => {
        const ctx = context({
            customConditions: [group([condition({ op: 'contains', value: 'special' })])],
        });
        expect(matchesToolFilter({ id: 1, name: 'A special tool' }, ctx, adapter)).toBe(true);
        expect(matchesToolFilter({ id: 2, name: 'A normal tool' }, ctx, adapter)).toBe(false);
    });

    it('skips customConditions when none have a usable value', () => {
        const ctx = context({
            customConditions: [group([condition({ op: 'contains', value: '' })])],
        });
        expect(matchesToolFilter({ id: 1, name: 'Anything' }, ctx, adapter)).toBe(true);
    });
});

describe('evaluateConditionGroups — key-based (ToolFieldMap)', () => {
    const fieldMap: ToolFieldMap = {
        name: ['My Tool'],
        description: ['A useful description'],
        label: ['backend', 'api/rest'],
    };

    it('matches a specific key when condition has a key', () => {
        const groups = [group([condition({ key: 'name', op: 'contains', value: 'Tool' })])];
        expect(evaluateConditionGroups(groups, fieldMap)).toBe(true);
    });

    it('does not match when key field does not contain the value', () => {
        const groups = [group([condition({ key: 'name', op: 'contains', value: 'description' })])];
        expect(evaluateConditionGroups(groups, fieldMap)).toBe(false);
    });

    it('falls back to all fields when key is empty', () => {
        const groups = [group([condition({ key: '', op: 'contains', value: 'useful' })])];
        expect(evaluateConditionGroups(groups, fieldMap)).toBe(true);
    });

    it('falls back to all fields when key does not exist in the map', () => {
        const groups = [group([condition({ key: 'nonexistent', op: 'contains', value: 'useful' })])];
        expect(evaluateConditionGroups(groups, fieldMap)).toBe(true);
    });

    it('matches label key specifically', () => {
        const groups = [group([condition({ key: 'label', op: 'contains', value: 'backend' })])];
        expect(evaluateConditionGroups(groups, fieldMap)).toBe(true);
    });

    it('does not match label value in name key', () => {
        const groups = [group([condition({ key: 'name', op: 'contains', value: 'backend' })])];
        expect(evaluateConditionGroups(groups, fieldMap)).toBe(false);
    });
});
