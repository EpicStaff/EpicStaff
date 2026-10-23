import { NodeType } from '@shared/models';

import { ConnectionModel } from '../models/connection.model';
import { NodeModel } from '../models/node.model';

export interface HoverContext {
    nodeIds: Set<string>;
    connectionIds: Set<string>;
}

function isCdtNode(node: NodeModel): boolean {
    return node.type === NodeType.TABLE || node.type === NodeType.CLASSIFICATION_TABLE;
}

/**
 * Returns all node IDs reachable by following outgoing connections from `startId`,
 * not including `startId` itself. Used to detect cyclic outgoing branches.
 */
function getForwardReachable(startId: string, outgoingMap: Map<string, ConnectionModel[]>): Set<string> {
    const reachable = new Set<string>();
    const visited = new Set<string>([startId]);
    const queue: string[] = [];

    for (const conn of outgoingMap.get(startId) ?? []) {
        if (!visited.has(conn.targetNodeId)) {
            visited.add(conn.targetNodeId);
            reachable.add(conn.targetNodeId);
            queue.push(conn.targetNodeId);
        }
    }

    while (queue.length > 0) {
        const current = queue.shift()!;
        for (const conn of outgoingMap.get(current) ?? []) {
            if (!visited.has(conn.targetNodeId)) {
                visited.add(conn.targetNodeId);
                reachable.add(conn.targetNodeId);
                queue.push(conn.targetNodeId);
            }
        }
    }

    return reachable;
}

/**
 * Returns true if `sourceId` has any backward path (not passing through `cdtId`) that
 * reaches a node outside `cycleNodes`.
 *
 * This distinguishes nodes that belong **exclusively** to a CDT's cyclic outgoing branch
 * (no external ancestors) from nodes that participate in the cycle but are also reachable
 * from outside it (e.g., via a predecessor CDT or a different upstream branch).
 *
 * Nodes with an external ancestor must NOT be excluded from the backward context.
 */
function hasPathFromOutsideCycle(
    sourceId: string,
    cdtId: string,
    cycleNodes: Set<string>,
    incomingMap: Map<string, ConnectionModel[]>
): boolean {
    const visited = new Set<string>([sourceId]);
    const queue: string[] = [sourceId];

    while (queue.length > 0) {
        const current = queue.shift()!;
        for (const conn of incomingMap.get(current) ?? []) {
            const pred = conn.sourceNodeId;
            if (pred === cdtId) continue; // Do not cross back through the CDT itself
            if (!cycleNodes.has(pred)) return true; // Found a node outside the cycle
            if (!visited.has(pred)) {
                visited.add(pred);
                queue.push(pred);
            }
        }
    }

    return false;
}

/**
 * Computes the backward context starting from `targetId`.
 * Includes the target node, all valid predecessors, and their incoming connections.
 *
 * CDT rule: when a CDT node is encountered during backward traversal, incoming source
 * nodes that are **exclusively** reachable through the CDT's own cyclic outgoing branches
 * are excluded, together with their connections.
 *
 * A source node is considered exclusive to the cycle only if it has no backward path
 * (ignoring the CDT itself) that reaches a node outside the CDT's forward-reachable set.
 * If the source has any external ancestor it is included regardless of cycle membership.
 */
export function computeBackwardContext(
    targetId: string,
    nodeMap: Map<string, NodeModel>,
    incomingMap: Map<string, ConnectionModel[]>,
    outgoingMap: Map<string, ConnectionModel[]>
): HoverContext {
    const nodeIds = new Set<string>([targetId]);
    const connectionIds = new Set<string>();
    const visitedNodes = new Set<string>([targetId]);
    const queue: string[] = [targetId];

    while (queue.length > 0) {
        const currentId = queue.shift()!;
        const currentNode = nodeMap.get(currentId);

        // For CDT nodes: pre-compute which nodes are reachable via outgoing connections
        // so we can identify cyclic outgoing branch members.
        const forwardReachable =
            currentNode && isCdtNode(currentNode) ? getForwardReachable(currentId, outgoingMap) : null;

        for (const conn of incomingMap.get(currentId) ?? []) {
            const sourceId = conn.sourceNodeId;

            // Self-loop on a CDT: the outgoing connection comes back to the CDT itself.
            // Always treat it as a cyclic outgoing branch — exclude it.
            if (forwardReachable !== null && sourceId === currentId) {
                continue;
            }

            // Source is reachable through the CDT's outgoing branches.
            // Exclude it only if it has no ancestors outside the cycle (i.e., it is
            // exclusively part of the cyclic branch and not a genuine upstream node).
            if (forwardReachable !== null && forwardReachable.has(sourceId)) {
                if (!hasPathFromOutsideCycle(sourceId, currentId, forwardReachable, incomingMap)) {
                    continue;
                }
            }

            connectionIds.add(conn.id);
            nodeIds.add(sourceId);

            if (!visitedNodes.has(sourceId)) {
                visitedNodes.add(sourceId);
                queue.push(sourceId);
            }
        }
    }

    return { nodeIds, connectionIds };
}

/**
 * Computes the forward context starting from `targetId`.
 * Includes the target node, all reachable successors, and all outgoing connections.
 * Connections to already-visited nodes are still included; the visited node is just
 * not re-processed (prevents infinite loops in cyclic graphs).
 *
 * `backwardNodeIds` acts as a boundary: when a node other than `targetId` was
 * already captured by the backward traversal, it is included in the context but
 * its outgoing connections are not expanded further. This prevents the forward
 * pass from wrapping around through already-known upstream nodes.
 */
export function computeForwardContext(
    targetId: string,
    outgoingMap: Map<string, ConnectionModel[]>,
    backwardNodeIds: Set<string> = new Set()
): HoverContext {
    const nodeIds = new Set<string>([targetId]);
    const connectionIds = new Set<string>();
    const visitedNodes = new Set<string>([targetId]);
    const queue: string[] = [targetId];

    while (queue.length > 0) {
        const currentId = queue.shift()!;

        // Nodes already in the backward context (except the hovered node itself)
        // act as terminals: included in the context but not expanded further.
        if (currentId !== targetId && backwardNodeIds.has(currentId)) {
            continue;
        }

        for (const conn of outgoingMap.get(currentId) ?? []) {
            const nextId = conn.targetNodeId;

            // Always include the connection and its destination node.
            connectionIds.add(conn.id);
            nodeIds.add(nextId);

            // Only queue unvisited nodes to avoid reprocessing.
            if (!visitedNodes.has(nextId)) {
                visitedNodes.add(nextId);
                queue.push(nextId);
            }
        }
    }

    return { nodeIds, connectionIds };
}

/**
 * Builds the index maps needed by the traversal functions.
 */
function buildConnectionMaps(connections: ConnectionModel[]): {
    incomingMap: Map<string, ConnectionModel[]>;
    outgoingMap: Map<string, ConnectionModel[]>;
} {
    const incomingMap = new Map<string, ConnectionModel[]>();
    const outgoingMap = new Map<string, ConnectionModel[]>();

    for (const conn of connections) {
        if (!incomingMap.has(conn.targetNodeId)) incomingMap.set(conn.targetNodeId, []);
        incomingMap.get(conn.targetNodeId)!.push(conn);

        if (!outgoingMap.has(conn.sourceNodeId)) outgoingMap.set(conn.sourceNodeId, []);
        outgoingMap.get(conn.sourceNodeId)!.push(conn);
    }

    return { incomingMap, outgoingMap };
}

/**
 * Computes the full hover context for the hovered node by merging the backward
 * (predecessors) and forward (successors) traversal results.
 */
export function computeHoverContext(
    targetId: string,
    nodes: NodeModel[],
    connections: ConnectionModel[]
): HoverContext {
    const nodeMap = new Map<string, NodeModel>(nodes.map((n) => [n.id, n]));
    const { incomingMap, outgoingMap } = buildConnectionMaps(connections);

    const backward = computeBackwardContext(targetId, nodeMap, incomingMap, outgoingMap);
    const forward = computeForwardContext(targetId, outgoingMap, backward.nodeIds);

    return {
        nodeIds: new Set([...backward.nodeIds, ...forward.nodeIds]),
        connectionIds: new Set([...backward.connectionIds, ...forward.connectionIds]),
    };
}
