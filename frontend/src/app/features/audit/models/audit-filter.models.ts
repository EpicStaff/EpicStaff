import { AuditEventKind, AuditEventStatus, AuditNodeType, AuditRunBucket } from './audit-session.models';

export type AuditFilterOp = 'equals' | 'not_equal' | 'in' | 'not_in' | 'contains' | 'gt' | 'gte' | 'lt' | 'lte';

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

export interface AuditFilterState {
    kinds: AuditEventKind[];
    flowNames: string[];
    statuses: AuditEventStatus[];
    dateFrom: string | null;
    dateTo: string | null;
    nodeTypes: AuditNodeType[];
    runTypes: AuditRunBucket[];
}

export type AuditFilterNode = AuditFilterLeaf | AuditFilterGroup | AuditFilterNot;

export const EMPTY_AUDIT_FILTER: AuditFilterState = {
    kinds: [],
    flowNames: [],
    statuses: [],
    dateFrom: null,
    dateTo: null,
    nodeTypes: [],
    runTypes: [],
};
