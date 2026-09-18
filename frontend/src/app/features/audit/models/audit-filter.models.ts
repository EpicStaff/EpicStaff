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

export interface AuditIdFilter {
    mode: AuditIdMode;
    from: string;
    to: string;
    value: string;
    values: string[];
}

export interface AuditFilterState {
    kinds: AuditEventKind[];
    statuses: AuditEventStatus[];
    dateFrom: string | null;
    dateTo: string | null;
    nodeTypes: AuditNodeType[];
    runTypes: AuditRunBucket[];
    flow: AuditValuesFilter;
    id: AuditIdFilter;
    error: AuditCondition[];
    input: AuditCondition[];
    output: AuditCondition[];
    details: AuditCondition[];
}

export type AuditFilterNode = AuditFilterLeaf | AuditFilterGroup | AuditFilterNot;

export const EMPTY_AUDIT_FILTER: AuditFilterState = {
    kinds: [],
    statuses: [],
    dateFrom: null,
    dateTo: null,
    nodeTypes: [],
    runTypes: [],
    flow: { op: 'in', values: [] },
    id: { mode: 'in', from: '', to: '', value: '', values: [] },
    error: [createAuditCondition()],
    input: [createAuditCondition()],
    output: [createAuditCondition()],
    details: [createAuditCondition()],
};

export function createAuditCondition(): AuditCondition {
    return { id: generateUuid(), join: 'and', key: '', op: 'contains', value: '' };
}

export const VALUE_FREE_OPS: AuditFilterOp[] = ['is_empty', 'is_not_empty', 'key_exists', 'key_not_exists'];

export function isUsableCondition(condition: AuditCondition): boolean {
    return VALUE_FREE_OPS.includes(condition.op) || condition.value !== '';
}
