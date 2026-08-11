/**
 * Tools list page filter/sort model. Kept feature-local for now (mirrors the
 * shape in `features/flows/models/flow-filter.model.ts`) — may be lifted to
 * `@shared/models` once flows and tools converge on a common filter primitive.
 */

export type ToolSortOrder =
    | 'default'
    | 'name_asc'
    | 'name_desc'
    | 'used_in_projects'
    | 'used_in_agents'
    | 'most_used'
    | 'unused_first';

export type FilterOperator =
    | 'equals'
    | 'not_equals'
    | 'starts_with'
    | 'not_starts_with'
    | 'ends_with'
    | 'not_ends_with'
    | 'contains'
    | 'not_contains';

export type LogicalCombinator = 'AND' | 'OR';

export type CustomFilterScope = 'tool_name' | 'label_name';

export interface CustomFilterClause {
    operator: FilterOperator;
    value: string;
}

export interface CustomFilterCondition {
    scope: CustomFilterScope;
    primary: CustomFilterClause;
    combinator: LogicalCombinator;
    secondary?: CustomFilterClause;
}

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

export const FILTER_OPERATOR_LABELS: Record<FilterOperator, string> = {
    equals: 'Equals',
    not_equals: 'Does not equal',
    starts_with: 'Starts with',
    not_starts_with: "Doesn't start with",
    ends_with: 'Ends with',
    not_ends_with: 'Does not end with',
    contains: 'Contains',
    not_contains: 'Does not contain',
};

export const FILTER_OPERATOR_ORDER: FilterOperator[] = [
    'equals',
    'not_equals',
    'starts_with',
    'not_starts_with',
    'ends_with',
    'not_ends_with',
    'contains',
    'not_contains',
];

/** Sort orders that require per-tool usage counts to compute. */
export const USAGE_DEPENDENT_SORTS: readonly ToolSortOrder[] = [
    'used_in_projects',
    'used_in_agents',
    'most_used',
    'unused_first',
];

/**
 * Evaluate a text against a single {@link CustomFilterCondition}. Values are
 * compared case-insensitively; an empty condition (no primary value) always
 * matches, mirroring the behaviour of the flows custom filter.
 */
export function evaluateCustomCondition(text: string, condition: CustomFilterCondition | null): boolean {
    if (!condition) return true;
    const primary = condition.primary.value.trim();
    if (!primary) return true;
    const matchesPrimary = evaluateClause(text, condition.primary);
    const secondary = condition.secondary?.value.trim();
    if (!secondary || !condition.secondary) return matchesPrimary;
    const matchesSecondary = evaluateClause(text, condition.secondary);
    return condition.combinator === 'AND' ? matchesPrimary && matchesSecondary : matchesPrimary || matchesSecondary;
}

function evaluateClause(text: string, clause: CustomFilterClause): boolean {
    const haystack = text.toLowerCase();
    const needle = clause.value.trim().toLowerCase();
    switch (clause.operator) {
        case 'equals':
            return haystack === needle;
        case 'not_equals':
            return haystack !== needle;
        case 'starts_with':
            return haystack.startsWith(needle);
        case 'not_starts_with':
            return !haystack.startsWith(needle);
        case 'ends_with':
            return haystack.endsWith(needle);
        case 'not_ends_with':
            return !haystack.endsWith(needle);
        case 'contains':
            return haystack.includes(needle);
        case 'not_contains':
            return !haystack.includes(needle);
    }
}
