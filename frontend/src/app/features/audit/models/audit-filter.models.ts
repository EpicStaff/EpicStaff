import { AuditEventKind, AuditEventStatus, AuditNodeType, AuditRunBucket } from './audit-session.models';

export type AuditFilterOp = 'equals' | 'not_equal' | 'in' | 'not_in' | 'contains' | 'gt' | 'gte' | 'lt' | 'lte';

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
    op: string;
    values: string[];
}

export interface AuditTextFilter {
    op: string;
    value: string;
}

export interface AuditJsonFilter {
    key: string;
    op: string;
    value: string;
}

export interface AuditFilterState {
    kinds: AuditEventKind[];
    statuses: AuditEventStatus[];
    dateFrom: string | null;
    dateTo: string | null;
    nodeTypes: AuditNodeType[];
    runTypes: AuditRunBucket[];
    flow: AuditValuesFilter;
    id: AuditValuesFilter;
    error: AuditTextFilter;
    input: AuditJsonFilter;
    output: AuditJsonFilter;
    details: AuditJsonFilter;
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
    id: { op: 'in', values: [] },
    error: { op: 'is_not_empty', value: '' },
    input: { key: '', op: 'contains', value: '' },
    output: { key: '', op: 'contains', value: '' },
    details: { key: '', op: 'contains', value: '' },
};
