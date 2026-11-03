import { EMPTY_FLOWS_FILTER, FlowsFilterState } from '../models/flow-filter.model';

/**
 * Shape accepted by the backend validator.
 * Only includes the keys allowed by `validate_flow_filter_body_shape`.
 */
export interface FlowPresetBody {
    [key: string]: unknown;
    sortOrder: string;
    includedFlowIds: number[] | null;
    includedLabelIds: number[] | null;
    customConditions: unknown[] | null;
}

/** Snapshot the current filter state for persisting as a preset body. */
export function buildFlowPresetBody(state: FlowsFilterState): FlowPresetBody {
    return {
        sortOrder: state.sortOrder,
        includedFlowIds: state.includedFlowIds,
        includedLabelIds: state.includedLabelIds,
        customConditions: state.customConditions,
    };
}

/** Merge a (possibly incomplete) saved body over defaults for forward compatibility. */
export function restoreFlowPresetState(body: Record<string, unknown>): FlowsFilterState {
    const mapped: Partial<FlowsFilterState> = {};

    if ('sortOrder' in body && typeof body['sortOrder'] === 'string')
        mapped.sortOrder = body['sortOrder'] as FlowsFilterState['sortOrder'];
    if ('includedFlowIds' in body && (Array.isArray(body['includedFlowIds']) || body['includedFlowIds'] === null))
        mapped.includedFlowIds = body['includedFlowIds'] as number[] | null;
    if ('includedLabelIds' in body && (Array.isArray(body['includedLabelIds']) || body['includedLabelIds'] === null))
        mapped.includedLabelIds = body['includedLabelIds'] as number[] | null;
    if ('customConditions' in body && (Array.isArray(body['customConditions']) || body['customConditions'] === null))
        mapped.customConditions = body['customConditions'] as FlowsFilterState['customConditions'];

    return { ...EMPTY_FLOWS_FILTER, ...mapped };
}
