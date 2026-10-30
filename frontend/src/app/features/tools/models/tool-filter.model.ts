import { AuditConditionGroup, createAuditConditionGroup } from '../../audit/models/audit-filter.models';

export type ToolSortOrder = 'default' | 'last_modified' | 'name_asc' | 'name_desc' | 'most_used' | 'unused_first';

export type UsageBucket = 'agent_surface' | 'shared_surface' | 'inline_surface';

export interface ToolsFilterState {
    showFavoriteOnly: boolean;
    showNotFavoriteOnly: boolean;
    sourceBuiltIn: boolean;
    sourceCustom: boolean;
    usageBuckets: readonly UsageBucket[];
    unusedOnly: boolean;
    sortOrder: ToolSortOrder;
    includedToolIds: number[] | null; // null = all
    includedLabelIds: number[] | null; // null = all
    customConditions: AuditConditionGroup[];
}

export const EMPTY_TOOLS_FILTER: ToolsFilterState = {
    showFavoriteOnly: false,
    showNotFavoriteOnly: false,
    sourceBuiltIn: false,
    sourceCustom: false,
    usageBuckets: [],
    unusedOnly: false,
    sortOrder: 'default',
    includedToolIds: null,
    includedLabelIds: null,
    customConditions: [createAuditConditionGroup()],
};

/** Sort orders that require per-tool usage counts to compute. */
export const USAGE_DEPENDENT_SORTS: readonly ToolSortOrder[] = ['most_used', 'unused_first'];
