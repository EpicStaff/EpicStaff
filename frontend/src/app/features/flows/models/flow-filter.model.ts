import { CustomFilterCondition as SharedCustomFilterCondition } from '@shared/models';

import { AuditConditionGroup, createAuditConditionGroup } from '../../audit/models/audit-filter.models';

export type { CustomFilterClause, FilterOperator, LogicalCombinator } from '@shared/models';
export { evaluateCustomCondition, FILTER_OPERATOR_LABELS, FILTER_OPERATOR_ORDER } from '@shared/models';

export type FlowSortOrder = 'default' | 'name_asc' | 'name_desc' | 'last_modified';

export type CustomFilterScope = 'flow_name' | 'label_name';

/** Flows-scoped alias of the shared generic condition. */
export type CustomFilterCondition = SharedCustomFilterCondition<CustomFilterScope>;

export interface FlowsFilterState {
    searchTerm: string;
    sortOrder: FlowSortOrder;
    includedFlowIds: number[] | null;
    includedLabelIds: number[] | null;
    customConditions: AuditConditionGroup[];
    customFilter?: CustomFilterCondition | null;
}

export const EMPTY_FLOWS_FILTER: FlowsFilterState = {
    searchTerm: '',
    sortOrder: 'default',
    includedFlowIds: null,
    includedLabelIds: null,
    customConditions: [createAuditConditionGroup()],
};
