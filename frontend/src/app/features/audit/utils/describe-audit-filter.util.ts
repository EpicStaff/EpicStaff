import { AuditEnumOption, AuditFilterState, AuditIdFilter, AuditIdMode } from '../models/audit-filter.models';
import {
    ID_MODE_OPTIONS,
    KIND_OPTIONS,
    NODE_TYPE_OPTIONS,
    OPERATOR_LABELS,
    RUN_TYPE_OPTIONS,
    STATUS_OPTIONS,
} from '../models/audit-filter-options';

export interface AuditFilterChip {
    key: string;
    label: string;
    value: string;
}

function labelsFor(values: string[], options: AuditEnumOption[]): string {
    return values.map((value) => options.find((option) => option.value === value)?.label ?? value).join(', ');
}

function idModeLabel(mode: AuditIdMode): string {
    return ID_MODE_OPTIONS.find((option) => option.value === mode)?.label ?? mode;
}

function describeId(id: AuditIdFilter): string | null {
    if (id.mode === 'range') {
        if (id.from !== '' && id.to !== '') {
            return `${id.from} — ${id.to}`;
        }
        if (id.from !== '') {
            return `from ${id.from}`;
        }
        if (id.to !== '') {
            return `until ${id.to}`;
        }
        return null;
    }

    if (id.mode === 'in') {
        return id.values.length > 0 ? id.values.join(', ') : null;
    }

    if (id.value === '') {
        return null;
    }

    return id.mode === 'equals' ? id.value : `${idModeLabel(id.mode)} ${id.value}`;
}

export function describeAuditFilter(state: AuditFilterState): AuditFilterChip[] {
    const chips: AuditFilterChip[] = [];

    if (state.kinds.length > 0) {
        chips.push({ key: 'kind', label: 'Kind', value: labelsFor(state.kinds, KIND_OPTIONS) });
    }

    if (state.flow.values.length > 0) {
        chips.push({
            key: 'flow',
            label: 'Flow',
            value: `${OPERATOR_LABELS[state.flow.op]} ${state.flow.values.join(', ')}`,
        });
    }

    const idValue = describeId(state.id);
    if (idValue !== null) {
        chips.push({ key: 'id', label: 'ID', value: idValue });
    }

    if (state.statuses.length > 0) {
        chips.push({ key: 'status', label: 'Status', value: labelsFor(state.statuses, STATUS_OPTIONS) });
    }

    if (state.nodeTypes.length > 0) {
        chips.push({ key: 'nodeType', label: 'Node Type', value: labelsFor(state.nodeTypes, NODE_TYPE_OPTIONS) });
    }

    if (state.runTypes.length > 0) {
        chips.push({ key: 'run', label: 'Run', value: labelsFor(state.runTypes, RUN_TYPE_OPTIONS) });
    }

    return chips;
}

export function clearAuditFilterField(state: AuditFilterState, key: string): AuditFilterState {
    switch (key) {
        case 'kind':
            return { ...state, kinds: [] };
        case 'flow':
            return { ...state, flow: { op: 'in', values: [] } };
        case 'id':
            return { ...state, id: { mode: 'in', from: '', to: '', value: '', values: [] } };
        case 'status':
            return { ...state, statuses: [] };
        case 'nodeType':
            return { ...state, nodeTypes: [] };
        case 'run':
            return { ...state, runTypes: [] };
        default:
            return state;
    }
}
