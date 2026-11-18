import { generateUuid } from '@shared/utils';

import { AuditTextField } from './audit-domain.models';
import { DEEP_TEXT_OPERATORS, ERROR_OPERATORS, JSON_OPERATORS } from './audit-filter-options';
import { AuditEventKind, AuditEventStatus, AuditNodeType } from './audit-session.models';

export type AuditFilterOp =
    | 'equals'
    | 'not_equal'
    | 'in'
    | 'not_in'
    | 'contains'
    | 'gt'
    | 'gte'
    | 'lt'
    | 'lte'
    | 'starts_with'
    | 'ends_with'
    | 'not_contains'
    | 'is_empty'
    | 'is_not_empty'
    | 'key_exists'
    | 'key_not_exists'
    | 'key_not_equals';

export interface AuditEnumOption {
    value: string;
    label: string;
    icon?: string;
    // Tabler font icon (e.g. "ti ti-robot"), used for node types so they match the flow editor
    iconClass?: string;
    iconColor?: string;
}

export interface AuditNumberFilter {
    op: AuditFilterOp;
    value: string;
}

export interface AuditFilterLeaf {
    field: string;
    op: AuditFilterOp;
    value: unknown;
}

export interface AuditFilterGroup {
    op: 'and' | 'or';
    children: AuditFilterNode[];
}

export interface AuditFilterNot {
    op: 'not';
    child: AuditFilterNode;
}

export interface AuditValuesFilter {
    op: AuditFilterOp;
    values: string[];
}

export type AuditConditionJoin = 'and' | 'or';

export interface AuditCondition {
    id: string;
    join: AuditConditionJoin;
    key: string;
    op: AuditFilterOp;
    value: string;
}

export type AuditIdMode = 'range' | 'gt' | 'lt' | 'equals' | 'in';
export type AuditFilterMode = 'builder' | 'query';

export interface AuditIdFilter {
    mode: AuditIdMode;
    from: string;
    to: string;
    value: string;
    values: string[];
}

export interface AuditMatchScopeState {
    children: boolean;
    rowsBeforeEnabled: boolean;
    rowsBefore: number;
    fullSessionHistory: boolean;
}

export const DEFAULT_MATCH_SCOPE: AuditMatchScopeState = {
    children: false,
    rowsBeforeEnabled: false,
    rowsBefore: 1,
    fullSessionHistory: false,
};

export const MAX_ROWS_BEFORE = 20; // backend MatchScope.rows_before le=20

export interface AuditFilterState {
    mode: AuditFilterMode;
    query: string;
    searchText: string;
    matchScope: AuditMatchScopeState;
    kinds: AuditEventKind[];
    statuses: AuditEventStatus[];
    dateFrom: string | null;
    dateTo: string | null;
    nodeTypes: AuditNodeType[];
    flow: AuditValuesFilter;
    id: AuditIdFilter;
    error: AuditConditionGroup[];
    input: AuditConditionGroup[];
    output: AuditConditionGroup[];
    details: AuditConditionGroup[];
    agent: AuditValuesFilter;
    tool: AuditValuesFilter;
    task: AuditConditionGroup[];
    prompt: AuditConditionGroup[];
    messageText: AuditConditionGroup[];
    tokens: AuditNumberFilter;
    // Builder filters of a field catalog (user actions), by field name. Left out of the sessions filter,
    // so a sessions state saves and compiles exactly as before they existed.
    selections?: Record<string, AuditValuesFilter>;
    textConditions?: Record<string, AuditConditionGroup[]>;
    idFilters?: Record<string, AuditIdFilter>;
}

export interface AuditConditionGroup {
    id: string;
    join: AuditConditionJoin;
    conditions: AuditCondition[];
}
export type AuditFilterNode = AuditFilterLeaf | AuditFilterGroup | AuditFilterNot;

export const EMPTY_AUDIT_FILTER: AuditFilterState = {
    mode: 'builder',
    query: '',
    searchText: '',
    matchScope: DEFAULT_MATCH_SCOPE,
    kinds: [],
    statuses: [],
    dateFrom: null,
    dateTo: null,
    nodeTypes: [],
    flow: { op: 'in', values: [] },
    id: { mode: 'in', from: '', to: '', value: '', values: [] },
    error: [createAuditConditionGroup(ERROR_OPERATORS)],
    input: [createAuditConditionGroup(JSON_OPERATORS)],
    output: [createAuditConditionGroup(JSON_OPERATORS)],
    details: [createAuditConditionGroup(JSON_OPERATORS)],
    agent: { op: 'in', values: [] },
    tool: { op: 'in', values: [] },
    task: [createAuditConditionGroup(DEEP_TEXT_OPERATORS)],
    prompt: [createAuditConditionGroup(DEEP_TEXT_OPERATORS)],
    messageText: [createAuditConditionGroup(DEEP_TEXT_OPERATORS)],
    tokens: { op: 'gt', value: '' },
};

// Shared, so an unset catalog field hands the Builder the same empty value on every change detection.
const EMPTY_SELECTION: AuditValuesFilter = { op: 'in', values: [] };
const EMPTY_TEXT_CONDITIONS = new Map<AuditFilterOp, AuditConditionGroup[]>();

export function catalogSelection(state: AuditFilterState, field: string): AuditValuesFilter {
    return state.selections?.[field] ?? EMPTY_SELECTION;
}

export function catalogIdFilter(state: AuditFilterState, field: string): AuditIdFilter {
    return state.idFilters?.[field] ?? EMPTY_AUDIT_FILTER.id;
}

export function catalogTextConditions(state: AuditFilterState, textField: AuditTextField): AuditConditionGroup[] {
    const saved = state.textConditions?.[textField.field];
    if (saved !== undefined) {
        return saved;
    }
    const [firstOperator] = textField.operators;
    let empty = EMPTY_TEXT_CONDITIONS.get(firstOperator);
    if (empty === undefined) {
        empty = [createAuditConditionGroup(textField.operators)];
        EMPTY_TEXT_CONDITIONS.set(firstOperator, empty);
    }
    return empty;
}

// A new condition takes the first of its field's operators: one the field does not offer would still be
// sent, while its dropdown could not show it.
export function createAuditCondition(operators: AuditFilterOp[]): AuditCondition {
    return { id: generateUuid(), join: 'and', key: '', op: operators[0], value: '' };
}

export function createAuditConditionGroup(operators: AuditFilterOp[]): AuditConditionGroup {
    return { id: generateUuid(), join: 'or', conditions: [createAuditCondition(operators)] };
}

export function removeAuditCondition(
    groups: AuditConditionGroup[],
    groupId: string,
    conditionId: string
): AuditConditionGroup[] {
    const next = groups.map((group) =>
        group.id === groupId
            ? { ...group, conditions: group.conditions.filter((item) => item.id !== conditionId) }
            : group
    );
    const nonEmpty = next.filter((group) => group.conditions.length > 0);
    return nonEmpty.length > 0 ? nonEmpty : next.slice(0, 1);
}

// field the backend treats as full-text search across the event
export const FREE_TEXT_FIELD = '__text__';

export const VALUE_FREE_OPS: AuditFilterOp[] = ['is_empty', 'is_not_empty', 'key_exists', 'key_not_exists'];

export function isUsableCondition(condition: AuditCondition): boolean {
    return VALUE_FREE_OPS.includes(condition.op) || condition.value !== '';
}
