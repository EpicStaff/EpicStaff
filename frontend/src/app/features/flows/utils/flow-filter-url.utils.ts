import { Params } from '@angular/router';

import {
    CustomFilterCondition,
    CustomFilterScope,
    FILTER_OPERATOR_ORDER,
    FilterOperator,
    FlowsFilterState,
    FlowSortOrder,
    LogicalCombinator,
} from '../models/flow-filter.model';

const SORT_VALUES: FlowSortOrder[] = ['default', 'name_asc', 'name_desc'];
const SCOPE_VALUES: CustomFilterScope[] = ['flow_name', 'label_name'];
const COMBINATOR_VALUES: LogicalCombinator[] = ['AND', 'OR'];

function parseIdList(raw: string | null | undefined): number[] | null {
    if (!raw) return null;
    const ids = raw
        .split(',')
        .map((s) => Number.parseInt(s, 10))
        .filter((n) => Number.isFinite(n));
    return ids.length > 0 ? ids : null;
}

function parseCustomFilter(raw: string | null | undefined): CustomFilterCondition | null {
    if (!raw) return null;
    const parts = raw.split('|');
    if (parts.length < 3) return null;

    const scope = parts[0] as CustomFilterScope;
    const op1 = parts[1] as FilterOperator;
    const value1 = decodeURIComponent(parts[2] ?? '');

    if (!SCOPE_VALUES.includes(scope)) return null;
    if (!FILTER_OPERATOR_ORDER.includes(op1)) return null;

    const condition: CustomFilterCondition = {
        scope,
        primary: { operator: op1, value: value1 },
        combinator: 'AND',
    };

    if (parts.length >= 6) {
        const combinator = parts[3] as LogicalCombinator;
        const op2 = parts[4] as FilterOperator;
        const value2 = decodeURIComponent(parts[5] ?? '');
        if (COMBINATOR_VALUES.includes(combinator) && FILTER_OPERATOR_ORDER.includes(op2)) {
            condition.combinator = combinator;
            condition.secondary = { operator: op2, value: value2 };
        }
    }

    return condition;
}

function serializeCustomFilter(condition: CustomFilterCondition): string {
    const head = `${condition.scope}|${condition.primary.operator}|${encodeURIComponent(condition.primary.value)}`;
    if (!condition.secondary || !condition.secondary.value.trim()) return head;
    return `${head}|${condition.combinator}|${condition.secondary.operator}|${encodeURIComponent(
        condition.secondary.value
    )}`;
}

export function parseFilterFromParams(params: Params): FlowsFilterState {
    const sortRaw = params['sort'] as string | undefined;
    const sortOrder = SORT_VALUES.includes(sortRaw as FlowSortOrder) ? (sortRaw as FlowSortOrder) : 'default';

    return {
        searchTerm: typeof params['q'] === 'string' ? params['q'] : '',
        sortOrder,
        includedFlowIds: parseIdList(params['flows'] as string | undefined),
        includedLabelIds: parseIdList(params['labels'] as string | undefined),
        customFilter: parseCustomFilter(params['cf'] as string | undefined),
    };
}

export function serializeFilterToParams(state: FlowsFilterState): Params {
    const params: Params = {
        q: state.searchTerm ? state.searchTerm : null,
        sort: state.sortOrder !== 'default' ? state.sortOrder : null,
        flows: state.includedFlowIds && state.includedFlowIds.length > 0 ? state.includedFlowIds.join(',') : null,
        labels: state.includedLabelIds && state.includedLabelIds.length > 0 ? state.includedLabelIds.join(',') : null,
        cf: state.customFilter ? serializeCustomFilter(state.customFilter) : null,
    };
    return params;
}
