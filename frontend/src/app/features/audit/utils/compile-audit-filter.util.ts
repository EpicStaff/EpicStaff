import { AuditFilterLeaf, AuditFilterNode, AuditFilterState } from '../models/audit-filter.models';
import { AuditMatchScope } from '../models/audit-session.models';

const SESSION_ANCHOR: AuditFilterLeaf = {
    field: 'kind',
    op: 'in',
    value: ['session'],
};

const SESSION_END_ANCHOR: AuditFilterLeaf = {
    field: 'details.message_type',
    op: 'equals',
    value: 'session_end',
};

export interface CompiledAuditFilter {
    filters: AuditFilterNode;
    matchScope: AuditMatchScope;
}

export function compileAuditFilter(state: AuditFilterState): CompiledAuditFilter {
    const anchorOnSessionEnd = state.statuses.length > 0;
    const leaves: AuditFilterNode[] = [anchorOnSessionEnd ? SESSION_END_ANCHOR : SESSION_ANCHOR];

    if (state.flowNames.length > 0) {
        leaves.push({ field: 'flow_name', op: 'in', value: state.flowNames });
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

    return {
        filters: leaves.length === 1 ? leaves[0] : { op: 'and', children: leaves },
        matchScope: anchorOnSessionEnd ? { full_session_history: true } : { children: true },
    };
}
