import { AuditEnumOption } from './audit-filter.models';

export const KIND_OPTIONS: AuditEnumOption[] = [
    { value: 'session', label: 'Session' },
    { value: 'node', label: 'Node' },
    { value: 'event', label: 'Event' },
];

export const STATUS_OPTIONS: AuditEnumOption[] = [
    { value: 'completed', label: 'Completed' },
    { value: 'failed', label: 'Failed' },
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
};

export const FLOW_OPERATORS = ['in', 'not_in'];

export const ID_OPERATORS = ['in', 'not_in', 'equals', 'not_equal'];

export const ERROR_OPERATORS = ['contains', 'not_contains', 'starts_with', 'ends_with', 'is_empty', 'is_not_empty'];
