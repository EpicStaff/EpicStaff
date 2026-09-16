import { AuditEnumOption, AuditFilterState } from '../models/audit-filter.models';
import { KIND_OPTIONS, NODE_TYPE_OPTIONS, RUN_TYPE_OPTIONS, STATUS_OPTIONS } from '../models/audit-filter-options';

export interface AuditFilterChip {
    key: string;
    label: string;
    value: string;
}

function labelsFor(values: string[], options: AuditEnumOption[]): string {
    return values.map((value) => options.find((option) => option.value === value)?.label ?? value).join(', ');
}

export function describeAuditFilter(state: AuditFilterState): AuditFilterChip[] {
    const chips: AuditFilterChip[] = [];

    if (state.kinds.length > 0) {
        chips.push({ key: 'kind', label: 'Kind', value: labelsFor(state.kinds, KIND_OPTIONS) });
    }

    if (state.statuses.length > 0) {
        chips.push({ key: 'status', label: 'Status', value: labelsFor(state.statuses, STATUS_OPTIONS) });
    }

    if (state.nodeTypes.length > 0) {
        chips.push({ key: 'nodeType', label: 'Node Type', value: labelsFor(state.nodeTypes, NODE_TYPE_OPTIONS) });
    }

    if (state.runTypes.length > 0) {
        chips.push({ key: 'run', label: 'Run', value: labelsFor(state.runTypes, RUN_TYPE_OPTIONS) });
    }

    return chips;
}

export function clearAuditFilterField(state: AuditFilterState, key: string): AuditFilterState {
    switch (key) {
        case 'kind':
            return { ...state, kinds: [] };
        case 'status':
            return { ...state, statuses: [] };
        case 'nodeType':
            return { ...state, nodeTypes: [] };
        case 'run':
            return { ...state, runTypes: [] };
        default:
            return state;
    }
}
