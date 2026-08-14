/**
 * Shared primitives for the "custom filter" pattern used by list pages
 * (flows, tools, …). The dialog UI + per-feature filter state are still
 * feature-local, but the operator vocabulary, clause/condition shape, and
 * text-matching semantics live here so consumers stay in sync.
 *
 * The `scope` field on {@link CustomFilterCondition} is generic so each
 * feature can constrain it to its own union (e.g. `'flow_name' | 'label_name'`
 * for flows, `'tool_name' | 'label_name'` for tools).
 */

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

export interface CustomFilterClause {
    operator: FilterOperator;
    value: string;
}

export interface CustomFilterCondition<TScope extends string = string> {
    scope: TScope;
    primary: CustomFilterClause;
    combinator: LogicalCombinator;
    secondary?: CustomFilterClause;
}

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

/**
 * Evaluate a text (or list of texts) against a single
 * {@link CustomFilterCondition}. Values are compared case-insensitively; an
 * empty condition (no primary value) always matches. When an array is passed,
 * a clause matches if **any** element satisfies it (used for multi-value fields
 * like a row's list of label names).
 */
export function evaluateCustomCondition(text: string | string[], condition: CustomFilterCondition | null): boolean {
    if (!condition) return true;
    const primary = condition.primary.value.trim();
    if (!primary) return true;
    const haystacks = Array.isArray(text) ? text : [text];
    if (haystacks.length === 0) return false;
    const matchesPrimary = haystacks.some((h) => evaluateClause(h, condition.primary));
    const secondaryValue = condition.secondary?.value.trim();
    if (!secondaryValue || !condition.secondary) return matchesPrimary;
    const secondaryClause = condition.secondary;
    const matchesSecondary = haystacks.some((h) => evaluateClause(h, secondaryClause));
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
