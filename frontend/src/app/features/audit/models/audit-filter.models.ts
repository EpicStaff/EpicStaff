import { generateUuid } from '@shared/utils';

import { AuditEventKind, AuditEventStatus, AuditNodeType, AuditRunBucket } from './audit-session.models';

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
    runTypes: AuditRunBucket[];
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
    messageThought: AuditConditionGroup[];
    tokens: AuditNumberFilter;
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
    runTypes: [],
    flow: { op: 'in', values: [] },
    id: { mode: 'in', from: '', to: '', value: '', values: [] },
    error: [createAuditConditionGroup()],
    input: [createAuditConditionGroup()],
    output: [createAuditConditionGroup()],
    details: [createAuditConditionGroup()],
    agent: { op: 'in', values: [] },
    tool: { op: 'in', values: [] },
    task: [createAuditConditionGroup()],
    prompt: [createAuditConditionGroup()],
    messageText: [createAuditConditionGroup()],
    messageThought: [createAuditConditionGroup()],
    tokens: { op: 'gt', value: '' },
};

export function createAuditCondition(): AuditCondition {
    return { id: generateUuid(), join: 'and', key: '', op: 'contains', value: '' };
}

export function createAuditConditionGroup(): AuditConditionGroup {
    return { id: generateUuid(), join: 'or', conditions: [createAuditCondition()] };
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

export const VALUE_FREE_OPS: AuditFilterOp[] = ['is_empty', 'is_not_empty', 'key_exists', 'key_not_exists'];

export function isUsableCondition(condition: AuditCondition): boolean {
    return VALUE_FREE_OPS.includes(condition.op) || condition.value !== '';
}
