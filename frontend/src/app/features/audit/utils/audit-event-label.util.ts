import { AuditSessionEvent } from '../models/audit-session.models';

const EVENT_TYPE_LABELS = new Map<string, string>([
    ['start', 'Start'],
    ['finish', 'Finish'],
    ['python', 'Python'],
    ['python_stream', 'Stream'],
    ['error', 'Error'],
    ['llm', 'LLM'],
    ['condition_group', 'Condition'],
    ['condition_group_manipulation', 'Condition update'],
    ['classification_prompt', 'Classification prompt'],
    ['agent_node_stream', 'Agent step'],
    ['task_node_stream', 'Task step'],
    ['extracted_chunks', 'Chunks'],
    ['subgraph_start', 'Subgraph start'],
    ['subgraph_finish', 'Subgraph finish'],
    ['session_start', 'Session start'],
    ['session_end', 'Session end'],
]);

function humanize(value: string): string {
    const spaced = value.replaceAll('_', ' ');
    return spaced.charAt(0).toUpperCase() + spaced.slice(1);
}

export function auditEventLabel(event: AuditSessionEvent): string | null {
    const messageType = event.details?.['message_type'];
    if (event.kind !== 'event' || typeof messageType !== 'string' || messageType.trim() === '') {
        return null;
    }
    const type = messageType.trim();
    return EVENT_TYPE_LABELS.get(type) ?? humanize(type);
}

export function auditNameLabel(event: AuditSessionEvent): string | null {
    const label = auditEventLabel(event);
    if (label === null || event.name.toLowerCase().includes(label.toLowerCase())) {
        return null;
    }
    return label;
}
