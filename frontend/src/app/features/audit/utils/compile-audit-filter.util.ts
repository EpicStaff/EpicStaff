import { AuditFilterNode, AuditFilterState } from '../models/audit-filter.models';
import { AuditMatchScope, AuditRunBucket, AuditRunType } from '../models/audit-session.models';

const MATCH_SCOPE: AuditMatchScope = { children: true };

const RUN_TYPES_BY_BUCKET: Record<AuditRunBucket, AuditRunType[]> = {
    manual: ['manual'],
    api: ['schedule', 'webhook', 'telegram', 'parent_flow'],
};

export interface AuditFilterQuery {
    filters?: AuditFilterNode;
    matchScope: AuditMatchScope;
}

export function compileAuditFilter(state: AuditFilterState): AuditFilterQuery {
    const leaves: AuditFilterNode[] = [];

    if (state.kinds.length > 0) {
        leaves.push({ field: 'kind', op: 'in', value: state.kinds });
    }

    if (state.flow.values.length > 0) {
        leaves.push({ field: 'flow_name', op: state.flow.op, value: state.flow.values });
    }

    const id = state.id;
    if (id.mode === 'range') {
        if (id.from !== '') {
            leaves.push({ field: 'session_id', op: 'gte', value: Number(id.from) });
        }
        if (id.to !== '') {
            leaves.push({ field: 'session_id', op: 'lte', value: Number(id.to) });
        }
    } else if (id.mode === 'in') {
        if (id.values.length > 0) {
            leaves.push({ field: 'session_id', op: 'in', value: id.values.map(Number) });
        }
    } else if (id.value !== '') {
        leaves.push({ field: 'session_id', op: id.mode, value: Number(id.value) });
    }

    if (state.statuses.length > 0) {
        leaves.push({ field: 'status', op: 'in', value: state.statuses });
    }

    if (state.dateFrom) {
        leaves.push({ field: 'event_time', op: 'gte', value: state.dateFrom });
    }

    if (state.dateTo) {
        leaves.push({ field: 'event_time', op: 'lte', value: state.dateTo });
    }

    if (state.nodeTypes.length > 0) {
        leaves.push({ field: 'node_type', op: 'in', value: state.nodeTypes });
    }

    if (state.runTypes.length > 0) {
        const runTypes = state.runTypes.flatMap((bucket) => RUN_TYPES_BY_BUCKET[bucket]);
        leaves.push({ field: 'run_type', op: 'in', value: runTypes });
    }

    if (leaves.length === 0) {
        return { matchScope: MATCH_SCOPE };
    }

    return {
        filters: leaves.length === 1 ? leaves[0] : { op: 'and', children: leaves },
        matchScope: MATCH_SCOPE,
    };
}
