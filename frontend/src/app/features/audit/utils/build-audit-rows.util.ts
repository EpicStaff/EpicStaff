import { AuditSessionEvent, AuditSessionRowStatus } from '../models/audit-session.models';

export interface AuditRow {
    event: AuditSessionEvent;
    depth: number;
    sessionStatus: AuditSessionRowStatus | null;
    hasChildren: boolean;
    parentIds: string[];
    ancestorLines: boolean[];
    isLastChild: boolean;
}

// Flattens the returned documents into display rows, keeping the session → node → event hierarchy as depth.
export function buildAuditRows(events: AuditSessionEvent[]): AuditRow[] {
    const byId = new Map(events.map((event) => [event.id, event]));
    const childrenByParent = new Map<string, AuditSessionEvent[]>();
    const roots: AuditSessionEvent[] = [];

    for (const event of events) {
        if (event.parent_id && byId.has(event.parent_id)) {
            const siblings = childrenByParent.get(event.parent_id);
            if (siblings) {
                siblings.push(event);
            } else {
                childrenByParent.set(event.parent_id, [event]);
            }
        } else {
            roots.push(event);
        }
    }
    const resolveSessionStatus = (event: AuditSessionEvent): AuditSessionRowStatus | null => {
        if (event.kind !== 'session') {
            return null;
        }
        return event.status ?? 'running';
    };

    const rows: AuditRow[] = [];

    // recursive function which pushes event as a row and does it for its every child
    const walk = (
        event: AuditSessionEvent,
        depth: number,
        parentIds: string[],
        ancestorLines: boolean[],
        isLastChild: boolean
    ): void => {
        const children = childrenByParent.get(event.id);
        rows.push({
            event,
            depth,
            sessionStatus: resolveSessionStatus(event),
            hasChildren: children !== undefined,
            parentIds,
            ancestorLines,
            isLastChild,
        });
        if (!children) {
            return;
        }
        const nextParents = [...parentIds, event.id];
        const nextLines = depth === 0 ? [] : [...ancestorLines, !isLastChild];
        const sorted = [...children].sort((a, b) => a.event_time.localeCompare(b.event_time));
        sorted.forEach((child, index) => {
            walk(child, depth + 1, nextParents, nextLines, index === sorted.length - 1);
        });
    };

    roots.forEach((root, index) => {
        walk(root, 0, [], [], index === roots.length - 1);
    });

    return rows;
}
