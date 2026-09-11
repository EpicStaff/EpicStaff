import { AUDIT_MESSAGE_TYPE, AuditSessionEvent, AuditSessionRow } from '../models/audit-session.models';

function messageType(event: AuditSessionEvent): string | null {
    const value = event.details?.['message_type'];
    return typeof value === 'string' ? value : null;
}

function toRow(sessionId: number, events: AuditSessionEvent[]): AuditSessionRow {
    const identity = events.find((event) => event.kind === 'session') ?? null;
    const start = events.find((event) => messageType(event) === AUDIT_MESSAGE_TYPE.sessionStart) ?? null;
    const end = events.find((event) => messageType(event) === AUDIT_MESSAGE_TYPE.sessionEnd) ?? null;
    const startTime = start?.event_time ?? identity?.event_time ?? null;
    const endTime = end?.event_time ?? null;

    return {
        sessionId,
        identityId: identity?.id ?? '',
        name: start?.name ?? '',
        flowName: identity?.flow_name || end?.flow_name || '',
        runType: identity?.run_type || end?.run_type || '',
        status: end?.status ?? 'running',
        startTime,
        endTime,
        durationMs: startTime && endTime ? new Date(endTime).getTime() - new Date(startTime).getTime() : null,
        output: end?.output ?? null,
        error: end?.error ?? null,
        details: end?.details ?? null,
        children: events.filter((event) => event !== identity),
    };
}

export function groupAuditSessions(events: AuditSessionEvent[]): AuditSessionRow[] {
    const order: number[] = [];
    const bySession = new Map<number, AuditSessionEvent[]>();

    for (const event of events) {
        const bucket = bySession.get(event.session_id);
        if (bucket) {
            bucket.push(event);
        } else {
            bySession.set(event.session_id, [event]);
            order.push(event.session_id);
        }
    }
    return order.map((sessionId) => toRow(sessionId, bySession.get(sessionId) ?? []));
}
