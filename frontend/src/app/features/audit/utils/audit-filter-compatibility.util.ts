import { AuditFilterState } from '../models/audit-filter.models';
import { AuditEventKind } from '../models/audit-session.models';

const ALL_KINDS: AuditEventKind[] = ['session', 'node', 'event'];

interface AuditFilterFieldMeta {
    kinds: AuditEventKind[];
    isActive: (state: AuditFilterState) => boolean;
}

// For each filter: which document kinds carry its field, and how to tell it is in use.
export const AUDIT_FILTER_FIELDS: Record<string, AuditFilterFieldMeta> = {
    flow: {
        kinds: ALL_KINDS,
        isActive: (state) => state.flowNames.length > 0,
    },
    status: {
        kinds: ['event'],
        isActive: (state) => state.statuses.length > 0,
    },
    date: {
        kinds: ALL_KINDS,
        isActive: (state) => state.dateFrom !== null || state.dateTo !== null,
    },
};

// shows whick kinds can still be chosen
export function allowedKinds(state: AuditFilterState): AuditEventKind[] {
    let allowed = ALL_KINDS;

    for (const meta of Object.values(AUDIT_FILTER_FIELDS)) {
        if (meta.isActive(state)) {
            allowed = allowed.filter((kind) => meta.kinds.includes(kind));
        }
    }

    return allowed;
}

//shows can filter be used with chosen kinds or not
export function isFieldEnabled(field: string, state: AuditFilterState): boolean {
    const meta = AUDIT_FILTER_FIELDS[field];
    if (!meta || state.kinds.length === 0) {
        return true;
    }
    return state.kinds.some((kind) => meta.kinds.includes(kind));
}
