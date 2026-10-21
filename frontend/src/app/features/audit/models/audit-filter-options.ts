import { NODE_COLORS, NODE_ICONS, NodeType } from '@shared/models';

import { auditNodeTypeLabel } from '../utils/audit-event-label.util';
import { AuditEnumOption, AuditFilterOp } from './audit-filter.models';

// same label as the table's Node Type column, so a type reads the same in both places
function nodeTypeOption(value: string, nodeType: NodeType): AuditEnumOption {
    return {
        value,
        label: auditNodeTypeLabel(value),
        iconClass: NODE_ICONS[nodeType],
        iconColor: NODE_COLORS[nodeType],
    };
}

export const KIND_OPTIONS: AuditEnumOption[] = [
    { value: 'session', label: 'Session' },
    { value: 'node', label: 'Node' },
    { value: 'event', label: 'Event' },
];

export const STATUS_OPTIONS: AuditEnumOption[] = [
    { value: 'completed', label: 'Completed', icon: 'check' },
    { value: 'failed', label: 'Failed', icon: 'x' },
];

export const NODE_TYPE_OPTIONS: AuditEnumOption[] = [
    nodeTypeOption('AGENT', NodeType.AGENT),
    nodeTypeOption('TASK', NodeType.TASK),
    nodeTypeOption('PYTHON', NodeType.PYTHON),
    nodeTypeOption('KNOWLEDGE', NodeType.KNOWLEDGE_RETRIEVER),
    nodeTypeOption('FILE_EXTRACTOR', NodeType.FILE_EXTRACTOR),
    nodeTypeOption('AUDIO_TRANSCRIPTION', NodeType.AUDIO_TO_TEXT),
    nodeTypeOption('DECISION_TABLE', NodeType.TABLE),
    nodeTypeOption('CLASSIFICATION_DECISION_TABLE', NodeType.CLASSIFICATION_TABLE),
    nodeTypeOption('END', NodeType.END),
    nodeTypeOption('SCHEDULE_TRIGGER', NodeType.SCHEDULE_TRIGGER),
    nodeTypeOption('WEBHOOK_TRIGGER', NodeType.WEBHOOK_TRIGGER),
    nodeTypeOption('TELEGRAM_TRIGGER', NodeType.TELEGRAM_TRIGGER),
];

export const OPERATOR_LABELS: Record<string, string> = {
    in: 'is any of',
    not_in: 'is none of',
    equals: 'is',
    not_equal: 'is not',
    contains: 'contains',
    not_contains: 'does not contain',
    starts_with: 'starts with',
    ends_with: 'ends with',
    is_empty: 'is empty',
    is_not_empty: 'is not empty',
    key_exists: 'has key',
    key_not_exists: 'has no key',
    key_not_equals: 'does not equal',
    gt: 'greater than',
    lt: 'less than',
    gte: 'greater or equal',
    lte: 'less or equal',
};

export const FLOW_OPERATORS: AuditFilterOp[] = ['in', 'not_in'];

export const ID_MODE_OPTIONS: AuditEnumOption[] = [
    { value: 'range', label: 'range' },
    { value: 'gt', label: 'more than' },
    { value: 'lt', label: 'less than' },
    { value: 'equals', label: 'exact ID' },
    { value: 'in', label: 'specific' },
];

export const ERROR_OPERATORS: AuditFilterOp[] = [
    'contains',
    'not_contains',
    'starts_with',
    'ends_with',
    'is_empty',
    'is_not_empty',
];

export const JOIN_OPTIONS: AuditEnumOption[] = [
    { value: 'and', label: 'AND' },
    { value: 'or', label: 'OR' },
];

export const JSON_OPERATORS: AuditFilterOp[] = [
    'equals',
    'key_not_equals',
    'contains',
    'not_contains',
    'starts_with',
    'ends_with',
    'key_exists',
    'key_not_exists',
    'gt',
    'gte',
    'lt',
    'lte',
];

export const DEEP_TEXT_OPERATORS: AuditFilterOp[] = [
    'contains',
    'not_contains',
    'starts_with',
    'ends_with',
    'equals',
    'not_equal',
];

export const TOKEN_OPERATORS: AuditFilterOp[] = ['gt', 'lt', 'equals', 'is_empty'];

export const TOKEN_OPERATOR_LABELS: Record<string, string> = {
    equals: 'equals',
};

export const TOKEN_STEP = 10;

export const QUERY_EXAMPLES: string[] = [
    'status in ["failed"] and node_type in ["AGENT", "PYTHON"]',
    'name == "Session Start"',
    'error is not empty and not session_id == 66',
    'input : order1234 and output : Greetings',
];

export interface QueryOperatorChip {
    label: string;
    text: string;
    // Where the cursor lands, counted back from the end of the inserted text; 0 or absent = after it.
    caretFromEnd?: number;
}

export const QUERY_OPERATORS: QueryOperatorChip[] = [
    { label: 'AND', text: ' and ' },
    { label: 'NOT', text: ' not ' },
    { label: 'IN', text: ' in ()', caretFromEnd: 1 },
    { label: 'OR', text: ' or ' },
    // the grammar only knows `is` as `is empty` / `is not empty`, so the chips insert the whole phrase
    { label: 'IS EMPTY', text: ' is empty' },
    { label: 'IS NOT EMPTY', text: ' is not empty' },
    { label: '>', text: ' > ' },
    { label: '<', text: ' < ' },
    { label: '==', text: ' == ' },
    { label: '!=', text: ' != ' },
];

export const QUERY_FIELDS: string[] = [
    'kind',
    'session_id',
    'name',
    'flow_name',
    'node_type',
    'status',
    'event_time',
    'duration',
    'input',
    'output',
    'error',
    'details',
    'agent',
    'task',
    'prompt',
    'message_text',
];
