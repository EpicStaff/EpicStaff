import { createAuditConditionGroup } from '../../audit/models/audit-filter.models';
import { EMPTY_TOOLS_FILTER, ToolsFilterState } from '../models/tool-filter.model';
import { describeToolFilter } from './describe-tool-filter.util';

function makeState(overrides: Partial<ToolsFilterState>): ToolsFilterState {
    return { ...EMPTY_TOOLS_FILTER, ...overrides };
}

describe('describeToolFilter', () => {
    it('returns no chips for default filter state', () => {
        expect(describeToolFilter(EMPTY_TOOLS_FILTER)).toEqual([]);
    });

    it('produces a Favorites chip when showFavorite is true', () => {
        const chips = describeToolFilter(makeState({ showFavorite: true }));
        expect(chips).toEqual([{ label: 'Favorites', value: 'Only' }]);
    });

    it('produces a Not Favorites chip when showNotFavorite is true', () => {
        const chips = describeToolFilter(makeState({ showNotFavorite: true }));
        expect(chips).toEqual([{ label: 'Not Favorites', value: 'Only' }]);
    });

    it('shows Source Built-in when only sourceBuiltIn is true', () => {
        const chips = describeToolFilter(makeState({ sourceBuiltIn: true }));
        expect(chips).toEqual([{ label: 'Source', value: 'Built-in' }]);
    });

    it('shows Source Custom when only sourceCustom is true', () => {
        const chips = describeToolFilter(makeState({ sourceCustom: true }));
        expect(chips).toEqual([{ label: 'Source', value: 'Custom' }]);
    });

    it('shows Source All when both sources are true', () => {
        const chips = describeToolFilter(makeState({ sourceBuiltIn: true, sourceCustom: true }));
        expect(chips).toEqual([{ label: 'Source', value: 'All' }]);
    });

    it('produces an Unused chip when unusedOnly is true', () => {
        const chips = describeToolFilter(makeState({ unusedOnly: true }));
        expect(chips).toEqual([{ label: 'Unused', value: 'Only' }]);
    });

    it('produces a Usage chip with bucket labels', () => {
        const chips = describeToolFilter(makeState({ usageBuckets: ['agent_surface', 'inline_surface'] }));
        expect(chips).toEqual([{ label: 'Usage', value: 'Agent, Inline' }]);
    });

    it('produces a Sort chip for non-default sort', () => {
        const chips = describeToolFilter(makeState({ sortOrder: 'name_asc' }));
        expect(chips).toEqual([{ label: 'Sort', value: 'Name A-Z' }]);
    });

    it('produces a Tools chip with selected count', () => {
        const chips = describeToolFilter(makeState({ includedToolIds: [1, 2, 3] }));
        expect(chips).toEqual([{ label: 'Tools', value: '3 selected' }]);
    });

    it('produces a Labels chip with selected count', () => {
        const chips = describeToolFilter(makeState({ includedLabelIds: [10, 20] }));
        expect(chips).toEqual([{ label: 'Labels', value: '2 selected' }]);
    });

    it('produces chips for usable custom conditions', () => {
        const group = {
            ...createAuditConditionGroup(),
            conditions: [{ id: '1', join: 'and' as const, key: 'name', op: 'contains' as const, value: 'test' }],
        };
        const chips = describeToolFilter(makeState({ customConditions: [group] }));
        expect(chips).toEqual([{ label: 'name', value: 'contains test' }]);
    });

    it('skips custom conditions with no value and non-value-free op', () => {
        const group = {
            ...createAuditConditionGroup(),
            conditions: [{ id: '1', join: 'and' as const, key: 'name', op: 'contains' as const, value: '' }],
        };
        const chips = describeToolFilter(makeState({ customConditions: [group] }));
        expect(chips).toEqual([]);
    });

    it('includes value-free ops like is_empty even without a value', () => {
        const group = {
            ...createAuditConditionGroup(),
            conditions: [{ id: '1', join: 'and' as const, key: 'name', op: 'is_empty' as const, value: '' }],
        };
        const chips = describeToolFilter(makeState({ customConditions: [group] }));
        expect(chips).toEqual([{ label: 'name', value: 'is empty' }]);
    });

    it('combines multiple active filters into multiple chips', () => {
        const chips = describeToolFilter(
            makeState({
                showFavorite: true,
                sourceBuiltIn: true,
                sortOrder: 'most_used',
            })
        );
        expect(chips).toHaveLength(3);
        expect(chips.map((chip) => chip.label)).toEqual(['Favorites', 'Source', 'Sort']);
    });
});
