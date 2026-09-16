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
