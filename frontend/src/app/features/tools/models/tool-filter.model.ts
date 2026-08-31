import { CustomFilterCondition as SharedCustomFilterCondition } from '@shared/models';

export type ToolSortOrder =
    | 'default'
    | 'name_asc'
    | 'name_desc'
    | 'used_in_projects'
    | 'used_in_agents'
    | 'most_used'
    | 'unused_first';

export type CustomFilterScope = 'tool_name' | 'label_name';

/** Tools-scoped alias of the shared generic condition. */
export type CustomFilterCondition = SharedCustomFilterCondition<CustomFilterScope>;

export interface ToolsFilterState {
    showFavoriteOnly: boolean;
    sortOrder: ToolSortOrder;
    includedToolIds: number[] | null; // null = all
    includedLabelIds: number[] | null; // null = all
    customFilter: CustomFilterCondition | null;
}

export const EMPTY_TOOLS_FILTER: ToolsFilterState = {
    showFavoriteOnly: false,
    sortOrder: 'default',
    includedToolIds: null,
    includedLabelIds: null,
    customFilter: null,
};

/** Sort orders that require per-tool usage counts to compute. */
export const USAGE_DEPENDENT_SORTS: readonly ToolSortOrder[] = [
    'used_in_projects',
    'used_in_agents',
    'most_used',
    'unused_first',
];
