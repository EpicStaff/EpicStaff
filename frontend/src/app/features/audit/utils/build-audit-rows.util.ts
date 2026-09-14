import {
    AUDIT_MESSAGE_TYPE,
    AuditEventStatus,
    AuditSessionEvent,
    AuditSessionRowStatus,
} from '../models/audit-session.models';

export interface AuditRow {
    event: AuditSessionEvent;
    depth: number;
    sessionStatus: AuditSessionRowStatus | null;
}

function messageType(event: AuditSessionEvent): string | null {
    const value = event.details?.['message_type'];
    return typeof value === 'string' ? value : null;
}

// Flattens the returned documents into display rows, keeping the session → node → event hierarchy as depth.
export function buildAuditRows(events: AuditSessionEvent[]): AuditRow[] {
    const byId = new Map(events.map((event) => [event.id, event]));
    const childrenByParent = new Map<string, AuditSessionEvent[]>();
    const roots: AuditSessionEvent[] = [];
    const endStatusBySession = new Map<number, AuditEventStatus>();
    const sessionsWithChildren = new Set<number>();

    for (const event of events) {
        if (event.parent_id && byId.has(event.parent_id)) {
            const siblings = childrenByParent.get(event.parent_id);
            if (siblings) {
                siblings.push(event);
            } else {
                childrenByParent.set(event.parent_id, [event]);
            }
            sessionsWithChildren.add(event.session_id);
        } else {
            roots.push(event);
        }

        if (messageType(event) === AUDIT_MESSAGE_TYPE.sessionEnd && event.status) {
            endStatusBySession.set(event.session_id, event.status);
        }
    }
    const resolveSessionStatus = (event: AuditSessionEvent): AuditSessionRowStatus | null => {
        if (event.kind !== 'session') {
            return null;
        }
        const ended = endStatusBySession.get(event.session_id);
        if (ended) {
            return ended;
        }
        return sessionsWithChildren.has(event.session_id) ? 'running' : null;
    };

    const rows: AuditRow[] = [];

    // recursive function which pushes event as a row and does it for its every child
    const walk = (event: AuditSessionEvent, depth: number): void => {
        rows.push({ event, depth, sessionStatus: resolveSessionStatus(event) });
        const children = childrenByParent.get(event.id);
        if (!children) {
            return;
        }
        for (const child of [...children].sort((a, b) => a.event_time.localeCompare(b.event_time))) {
            walk(child, depth + 1);
        }
    };

    for (const root of roots) {
        walk(root, 0);
    }

    return rows;
}
