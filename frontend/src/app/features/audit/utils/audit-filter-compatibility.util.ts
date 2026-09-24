import { AuditCondition, AuditFilterState, isUsableCondition } from '../models/audit-filter.models';
import { AuditEventKind } from '../models/audit-session.models';

const ALL_KINDS: AuditEventKind[] = ['session', 'node', 'event'];

interface AuditFilterFieldMeta {
    kinds: AuditEventKind[];
    isActive: (state: AuditFilterState) => boolean;
    conflictsWith?: string[];
}

// For each filter: which document kinds carry its field, and how to tell it is in use.
export const AUDIT_FILTER_FIELDS: Record<string, AuditFilterFieldMeta> = {
    flow: {
        kinds: ALL_KINDS,
        isActive: (state) => state.flow.values.length > 0,
    },
    status: {
        kinds: ['event'],
        isActive: (state) => state.statuses.length > 0,
    },
    date: {
        kinds: ALL_KINDS,
        isActive: (state) => state.dateFrom !== null || state.dateTo !== null,
    },
    nodeType: {
        kinds: ['node', 'event'],
        isActive: (state) => state.nodeTypes.length > 0,
    },
    run: {
        kinds: ['session', 'event'],
        isActive: (state) => state.runTypes.length > 0,
    },
    error: {
        kinds: ['event'],
        isActive: (state) => hasUsableCondition(state.error),
    },
    input: {
        kinds: ['event'],
        isActive: (state) => hasUsableCondition(state.input),
    },
    output: {
        kinds: ['event'],
        isActive: (state) => hasUsableCondition(state.output),
    },
    details: {
        kinds: ['event'],
        isActive: (state) => hasUsableCondition(state.details),
    },
    agent: {
        kinds: ['event'],
        isActive: (state) => state.agent.values.length > 0,
        conflictsWith: ['tool'],
    },
    tool: {
        kinds: ['event'],
        isActive: (state) => state.tool.values.length > 0,
        conflictsWith: ['agent'],
    },
    task: {
        kinds: ['event'],
        isActive: (state) => hasUsableCondition(state.task),
    },
    prompt: {
        kinds: ['event'],
        isActive: (state) => hasUsableCondition(state.prompt),
    },
    messageText: {
        kinds: ['event'],
        isActive: (state) => hasUsableCondition(state.messageText),
    },
    messageThought: {
        kinds: ['event'],
        isActive: (state) => hasUsableCondition(state.messageThought),
    },
    tokens: {
        kinds: ['event'],
        isActive: (state) => state.tokens.op === 'is_empty' || state.tokens.value !== '',
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

function hasUsableCondition(conditions: AuditCondition[]): boolean {
    return conditions.some(isUsableCondition);
}

//shows can filter be used with chosen kinds or not
export function isFieldEnabled(field: string, state: AuditFilterState): boolean {
    const meta = AUDIT_FILTER_FIELDS[field];
    if (!meta || state.kinds.length === 0) {
        return true;
    }
    return state.kinds.some((kind) => meta.kinds.includes(kind));
}

// same, plus filters that cannot be combined with this one because their fields
// never land on the same document
export function isFieldAvailable(field: string, state: AuditFilterState): boolean {
    const meta = AUDIT_FILTER_FIELDS[field];
    if (!meta) {
        return true;
    }
    const conflicts = meta.conflictsWith ?? [];
    return isFieldEnabled(field, state) && !conflicts.some((other) => AUDIT_FILTER_FIELDS[other]?.isActive(state));
}
