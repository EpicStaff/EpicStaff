import { NodeType } from '@shared/models';

import { AgentNodeTaskUi } from '../../core/models/agent-node.model';
import { FlowModel } from '../../core/models/flow.model';
import { AgentNodeModel, NodeModel } from '../../core/models/node.model';

/**
 * Drops backendId / edge id from nodes and connections that point at DB rows
 * which no longer exist in the last-saved baseline. This happens when a node or
 * edge is deleted, the deletion is saved, and then UNDO brings it back with its
 * now-stale id. Clearing the id (so it becomes null) makes the save treat the
 * item as brand-new, so the backend recreates it instead of rejecting an edge
 * that references a node that is already gone.
 *
 * Agent-node tasks get the same treatment: a task id that is not among the
 * baseline tasks of the same node is dropped (the task is then sent by its
 * tempId), and sibling context links to it are rewritten to that tempId.
 */
export function clearStaleIds(previous: FlowModel, current: FlowModel): FlowModel {
    const savedNodeIds = new Set<number>();
    for (const n of previous.nodes) if (n.backendId != null) savedNodeIds.add(n.backendId);

    const savedEdgeIds = new Set<number>();
    for (const c of previous.connections) if (c.data?.id != null) savedEdgeIds.add(c.data.id);

    const savedTaskIdsByNodeBackendId = new Map<number, Set<number>>();
    for (const n of previous.nodes) {
        if (n.type !== NodeType.AGENT || n.backendId == null) continue;
        const taskIds = new Set<number>();
        for (const task of n.data.tasks ?? []) if (task.id != null) taskIds.add(task.id);
        savedTaskIdsByNodeBackendId.set(n.backendId, taskIds);
    }

    const nodes = current.nodes.map((n) => {
        const nodeIsStale = n.backendId != null && !savedNodeIds.has(n.backendId);
        const cleared = nodeIsStale ? { ...n, backendId: null } : n;
        if (cleared.type !== NodeType.AGENT) return cleared;

        const savedTaskIds =
            n.backendId != null && !nodeIsStale ? savedTaskIdsByNodeBackendId.get(n.backendId) : undefined;
        return clearStaleTaskIds(cleared, savedTaskIds ?? new Set<number>());
    });
    const connections = current.connections.map((c) =>
        c.data?.id != null && !savedEdgeIds.has(c.data.id) ? { ...c, data: null } : c
    );

    return { ...current, nodes, connections };
}

function clearStaleTaskIds(node: AgentNodeModel, savedTaskIds: Set<number>): NodeModel {
    const tasks = node.data.tasks ?? [];
    const staleTempIdById = new Map<number, string>();
    for (const task of tasks) {
        if (task.id != null && !savedTaskIds.has(task.id)) staleTempIdById.set(task.id, task.tempId);
    }
    if (staleTempIdById.size === 0) return node;

    const rewritten = tasks.map((task): AgentNodeTaskUi => {
        const { id, ...withoutId } = task;
        const base = id != null && staleTempIdById.has(id) ? withoutId : task;
        const contextRefs = (task.contextRefs ?? []).map((ref) => {
            const tempId = ref.id != null ? staleTempIdById.get(ref.id) : undefined;
            return tempId != null ? { tempId } : ref;
        });
        return { ...base, contextRefs };
    });

    return { ...node, data: { ...node.data, tasks: rewritten } };
}
