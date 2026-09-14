import { AuditFilterNode, AuditFilterState } from '../models/audit-filter.models';
import { AuditMatchScope } from '../models/audit-session.models';

const MATCH_SCOPE: AuditMatchScope = { children: true, ancestors: true };

export interface AuditFilterQuery {
    filters?: AuditFilterNode;
    matchScope: AuditMatchScope;
}

export function compileAuditFilter(state: AuditFilterState): AuditFilterQuery {
    const leaves: AuditFilterNode[] = [];

    if (state.kinds.length > 0) {
        leaves.push({ field: 'kind', op: 'in', value: state.kinds });
    }

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

    if (leaves.length === 0) {
        return { matchScope: MATCH_SCOPE };
    }

    return {
        filters: leaves.length === 1 ? leaves[0] : { op: 'and', children: leaves },
        matchScope: MATCH_SCOPE,
    };
}
