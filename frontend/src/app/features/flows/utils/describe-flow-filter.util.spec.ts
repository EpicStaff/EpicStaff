import { createAuditConditionGroup } from '../../audit/models/audit-filter.models';
import { EMPTY_FLOWS_FILTER, FlowsFilterState } from '../models/flow-filter.model';
import { describeFlowFilter } from './describe-flow-filter.util';

function makeState(overrides: Partial<FlowsFilterState>): FlowsFilterState {
    return { ...EMPTY_FLOWS_FILTER, ...overrides };
}

describe('describeFlowFilter', () => {
    it('returns no chips for default filter state', () => {
        expect(describeFlowFilter(EMPTY_FLOWS_FILTER)).toEqual([]);
    });

    it('produces a Sort chip for non-default sort', () => {
        const chips = describeFlowFilter(makeState({ sortOrder: 'name_asc' }));
        expect(chips).toEqual([{ label: 'Sort', value: 'Name A-Z' }]);
    });

    it('produces a Flows chip with selected count', () => {
        const chips = describeFlowFilter(makeState({ includedFlowIds: [1, 2] }));
        expect(chips).toEqual([{ label: 'Flows', value: '2 selected' }]);
    });

    it('produces a Labels chip with selected count', () => {
        const chips = describeFlowFilter(makeState({ includedLabelIds: [10] }));
        expect(chips).toEqual([{ label: 'Labels', value: '1 selected' }]);
    });

    it('produces chips for usable custom conditions', () => {
        const group = {
            ...createAuditConditionGroup(),
            conditions: [{ id: '1', join: 'and' as const, key: 'flow_name', op: 'contains' as const, value: 'test' }],
        };
        const chips = describeFlowFilter(makeState({ customConditions: [group] }));
        expect(chips).toEqual([{ label: 'flow_name', value: 'contains test' }]);
    });

    it('skips custom conditions with no value and non-value-free op', () => {
        const group = {
            ...createAuditConditionGroup(),
            conditions: [{ id: '1', join: 'and' as const, key: 'name', op: 'contains' as const, value: '' }],
        };
        const chips = describeFlowFilter(makeState({ customConditions: [group] }));
        expect(chips).toEqual([]);
    });

    it('includes value-free ops like is_empty even without a value', () => {
        const group = {
            ...createAuditConditionGroup(),
            conditions: [{ id: '1', join: 'and' as const, key: 'name', op: 'is_empty' as const, value: '' }],
        };
        const chips = describeFlowFilter(makeState({ customConditions: [group] }));
        expect(chips).toEqual([{ label: 'name', value: 'is empty' }]);
    });

    it('handles all sort orders', () => {
        const sortOrders = ['name_asc', 'name_desc', 'last_modified'] as const;
        const expectedValues = ['Name A-Z', 'Name Z-A', 'Last Modified'];
        for (let index = 0; index < sortOrders.length; index++) {
            const chips = describeFlowFilter(makeState({ sortOrder: sortOrders[index] }));
            expect(chips[0].value).toBe(expectedValues[index]);
        }
    });

    it('combines multiple active filters into multiple chips', () => {
        const chips = describeFlowFilter(
            makeState({
                sortOrder: 'last_modified',
                includedFlowIds: [1],
                includedLabelIds: [2, 3],
            })
        );
        expect(chips).toHaveLength(3);
        expect(chips.map((chip) => chip.label)).toEqual(['Sort', 'Flows', 'Labels']);
    });
});
