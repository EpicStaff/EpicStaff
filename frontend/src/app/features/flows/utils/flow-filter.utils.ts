import { LabelDto } from '@shared/models';

import { CustomFilterClause, CustomFilterCondition, FilterOperator, FlowSortOrder } from '../models/flow-filter.model';
import { GetGraphLightRequest } from '../models/graph.model';

export function matchesOperator(haystack: string, operator: FilterOperator, needle: string): boolean {
    const h = haystack.toLowerCase();
    const n = needle.toLowerCase();
    switch (operator) {
        case 'equals':
            return h === n;
        case 'not_equals':
            return h !== n;
        case 'starts_with':
            return h.startsWith(n);
        case 'not_starts_with':
            return !h.startsWith(n);
        case 'ends_with':
            return h.endsWith(n);
        case 'not_ends_with':
            return !h.endsWith(n);
        case 'contains':
            return h.includes(n);
        case 'not_contains':
            return !h.includes(n);
    }
}

function clauseMatches(haystacks: string[], clause: CustomFilterClause): boolean {
    if (haystacks.length === 0) return false;
    return haystacks.some((h) => matchesOperator(h, clause.operator, clause.value));
}

export function evaluateCustomFilter(
    condition: CustomFilterCondition,
    flow: GetGraphLightRequest,
    labels: LabelDto[]
): boolean {
    const haystacks =
        condition.scope === 'flow_name'
            ? [flow.name]
            : (flow.label_ids ?? []).map((id) => labels.find((l) => l.id === id)?.name).filter((n): n is string => !!n);

    const primaryValue = condition.primary.value.trim();
    if (!primaryValue) return true;

    const primaryMatches = clauseMatches(haystacks, condition.primary);

    const secondary = condition.secondary;
    const secondaryValue = secondary?.value.trim() ?? '';
    if (!secondary || !secondaryValue) return primaryMatches;

    const secondaryMatches = clauseMatches(haystacks, secondary);
    return condition.combinator === 'AND' ? primaryMatches && secondaryMatches : primaryMatches || secondaryMatches;
}

export function compareFlowsByName(order: FlowSortOrder): (a: GetGraphLightRequest, b: GetGraphLightRequest) => number {
    if (order === 'name_asc') {
        return (a, b) => a.name.localeCompare(b.name, undefined, { sensitivity: 'base' });
    }
    if (order === 'name_desc') {
        return (a, b) => b.name.localeCompare(a.name, undefined, { sensitivity: 'base' });
    }
    return (a, b) => b.id - a.id;
}
