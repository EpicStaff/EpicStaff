import { AuditEnumOption, AuditFilterOp } from './audit-filter.models';

export const KIND_OPTIONS: AuditEnumOption[] = [
    { value: 'session', label: 'Session' },
    { value: 'node', label: 'Node' },
    { value: 'event', label: 'Event' },
];

export const STATUS_OPTIONS: AuditEnumOption[] = [
    { value: 'completed', label: 'Completed', icon: 'check' },
    { value: 'failed', label: 'Failed', icon: 'x' },
];

export const RUN_TYPE_OPTIONS: AuditEnumOption[] = [
    { value: 'manual', label: 'Manual' },
    { value: 'api', label: 'API' },
];

export const NODE_TYPE_OPTIONS: AuditEnumOption[] = [
    { value: 'AGENT', label: 'Agent' },
    { value: 'TASK', label: 'Task' },
    { value: 'PYTHON', label: 'Python' },
    { value: 'KNOWLEDGE', label: 'Knowledge' },
    { value: 'FILE_EXTRACTOR', label: 'File Extractor' },
    { value: 'AUDIO_TRANSCRIPTION', label: 'Audio Transcription' },
    { value: 'DECISION_TABLE', label: 'Decision Table' },
    { value: 'CLASSIFICATION_DECISION_TABLE', label: 'Classification Decision Table' },
    { value: 'END', label: 'End' },
    { value: 'SCHEDULE_TRIGGER', label: 'Schedule Trigger' },
    { value: 'WEBHOOK_TRIGGER', label: 'Webhook Trigger' },
    { value: 'TELEGRAM_TRIGGER', label: 'Telegram Trigger' },
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
