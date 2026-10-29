import { isUsableCondition } from '../../audit/models/audit-filter.models';
import { OPERATOR_LABELS } from '../../audit/models/audit-filter-options';
import { FlowsFilterState, FlowSortOrder } from '../models/flow-filter.model';

export interface FilterChip {
    label: string;
    value: string;
}

const SORT_ORDER_LABELS: Record<FlowSortOrder, string> = {
    default: 'Default',
    name_asc: 'Name A-Z',
    name_desc: 'Name Z-A',
    last_modified: 'Last Modified',
};

function describeConditionValue(condition: { op: string; value: string }): string {
    const operator = OPERATOR_LABELS[condition.op] ?? condition.op;
    return condition.value === '' ? operator : `${operator} ${condition.value}`;
}

export function describeFlowFilter(state: FlowsFilterState): FilterChip[] {
    const chips: FilterChip[] = [];

    if (state.sortOrder !== 'default') {
        chips.push({ label: 'Sort', value: SORT_ORDER_LABELS[state.sortOrder] ?? state.sortOrder });
    }

    if (state.includedFlowIds !== null) {
        chips.push({ label: 'Flows', value: `${state.includedFlowIds.length} selected` });
    }

    if (state.includedLabelIds !== null) {
        chips.push({ label: 'Labels', value: `${state.includedLabelIds.length} selected` });
    }

    for (const group of state.customConditions) {
        const usable = group.conditions.filter(isUsableCondition);
        for (const condition of usable) {
            chips.push({ label: condition.key || 'Condition', value: describeConditionValue(condition) });
        }
    }

    return chips;
}
