import { EMPTY_FLOWS_FILTER, FlowsFilterState } from '../models/flow-filter.model';
import { buildFlowPresetBody, FlowPresetBody, restoreFlowPresetState } from './flow-filter-preset-body.util';

describe('buildFlowPresetBody', () => {
    it('maps state to the backend body shape', () => {
        const state: FlowsFilterState = {
            ...EMPTY_FLOWS_FILTER,
            sortOrder: 'name_asc',
            includedFlowIds: [10, 20],
        };
        const body = buildFlowPresetBody(state);
        expect(body).toEqual({
            sortOrder: 'name_asc',
            includedFlowIds: [10, 20],
            includedLabelIds: null,
            customConditions: EMPTY_FLOWS_FILTER.customConditions,
        } satisfies FlowPresetBody);
        expect(body).not.toBe(state);
    });
});

describe('restoreFlowPresetState', () => {
    it('restores known keys from a saved body', () => {
        const result = restoreFlowPresetState({ sortOrder: 'name_desc', includedFlowIds: [1] });
        expect(result.sortOrder).toBe('name_desc');
        expect(result.includedFlowIds).toEqual([1]);
        expect(result.includedLabelIds).toBeNull();
        expect(result.customConditions).toEqual(EMPTY_FLOWS_FILTER.customConditions);
    });

    it('returns exact defaults for an empty body', () => {
        const result = restoreFlowPresetState({});
        expect(result).toEqual(EMPTY_FLOWS_FILTER);
    });

    it('round-trips through buildFlowPresetBody', () => {
        const state: FlowsFilterState = {
            ...EMPTY_FLOWS_FILTER,
            sortOrder: 'last_modified',
            includedLabelIds: [5, 6],
        };
        const restored = restoreFlowPresetState(buildFlowPresetBody(state));
        expect(restored).toEqual(state);
    });

    it('ignores unknown keys from the body', () => {
        const result = restoreFlowPresetState({ unknownKey: 'garbage', sortOrder: 'name_asc' });
        expect(result.sortOrder).toBe('name_asc');
        expect((result as unknown as Record<string, unknown>)['unknownKey']).toBeUndefined();
    });

    it('ignores values of wrong type', () => {
        const result = restoreFlowPresetState({ sortOrder: 123, includedFlowIds: 'not-an-array' });
        expect(result.sortOrder).toBe(EMPTY_FLOWS_FILTER.sortOrder);
        expect(result.includedFlowIds).toBeNull();
    });
});
