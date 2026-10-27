import { isUsableCondition } from '../../audit/models/audit-filter.models';
import { OPERATOR_LABELS } from '../../audit/models/audit-filter-options';
import { ToolsFilterState, ToolSortOrder, UsageBucket } from '../models/tool-filter.model';

export interface FilterChip {
    label: string;
    value: string;
}

const SORT_ORDER_LABELS: Record<ToolSortOrder, string> = {
    default: 'Default',
    last_modified: 'Last Modified',
    name_asc: 'Name A-Z',
    name_desc: 'Name Z-A',
    most_used: 'Most Used',
    unused_first: 'Unused First',
};

const USAGE_BUCKET_LABELS: Record<UsageBucket, string> = {
    agent_surface: 'Agent',
    shared_surface: 'Shared',
    inline_surface: 'Inline',
};

function describeConditionValue(condition: { op: string; value: string }): string {
    const operator = OPERATOR_LABELS[condition.op] ?? condition.op;
    return condition.value === '' ? operator : `${operator} ${condition.value}`;
}

export function describeToolFilter(state: ToolsFilterState): FilterChip[] {
    const chips: FilterChip[] = [];

    if (state.showFavorite) {
        chips.push({ label: 'Favorites', value: 'Only' });
    }
    if (state.showNotFavorite) {
        chips.push({ label: 'Not Favorites', value: 'Only' });
    }

    if (state.sourceBuiltIn && state.sourceCustom) {
        chips.push({ label: 'Source', value: 'All' });
    } else if (state.sourceBuiltIn) {
        chips.push({ label: 'Source', value: 'Built-in' });
    } else if (state.sourceCustom) {
        chips.push({ label: 'Source', value: 'Custom' });
    }

    if (state.unusedOnly) {
        chips.push({ label: 'Unused', value: 'Only' });
    }

    if (state.usageBuckets.length > 0) {
        const bucketLabels = state.usageBuckets.map((bucket) => USAGE_BUCKET_LABELS[bucket] ?? bucket).join(', ');
        chips.push({ label: 'Usage', value: bucketLabels });
    }

    if (state.sortOrder !== 'default') {
        chips.push({ label: 'Sort', value: SORT_ORDER_LABELS[state.sortOrder] ?? state.sortOrder });
    }

    if (state.includedToolIds !== null) {
        chips.push({ label: 'Tools', value: `${state.includedToolIds.length} selected` });
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
