import { FlowModel } from '../../core/models/flow.model';

/**
 * Drops backendId / edge id from nodes and connections that point at DB rows
 * which no longer exist in the last-saved baseline. This happens when a node or
 * edge is deleted, the deletion is saved, and then UNDO brings it back with its
 * now-stale id. Clearing the id (so it becomes null) makes the save treat the
 * item as brand-new, so the backend recreates it instead of rejecting an edge
 * that references a node that is already gone.
 */
export function clearStaleIds(previous: FlowModel, current: FlowModel): FlowModel {
    const savedNodeIds = new Set<number>();
    for (const n of previous.nodes) if (n.backendId != null) savedNodeIds.add(n.backendId);

    const savedEdgeIds = new Set<number>();
    for (const c of previous.connections) if (c.data?.id != null) savedEdgeIds.add(c.data.id);

    const nodes = current.nodes.map((n) =>
        n.backendId != null && !savedNodeIds.has(n.backendId) ? { ...n, backendId: null } : n
    );
    const connections = current.connections.map((c) =>
        c.data?.id != null && !savedEdgeIds.has(c.data.id) ? { ...c, data: null } : c
    );

    return { ...current, nodes, connections };
}
