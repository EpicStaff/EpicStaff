import { ConnectionModel } from '../core/models/connection.model';
import { FlowModel } from '../core/models/flow.model';
import { NodeModel } from '../core/models/node.model';

export interface FlowDiffResult {
    createdNodes: NodeModel[];
    updatedNodes: NodeModel[];
    deletedNodes: NodeModel[];
    createdConnections: ConnectionModel[];
    deletedConnections: ConnectionModel[];
}

export function diffFlowModels(before: FlowModel, after: FlowModel): FlowDiffResult {
    const beforeNodeById = new Map(before.nodes.map((n) => [n.id, n]));
    const afterNodeById = new Map(after.nodes.map((n) => [n.id, n]));

    const createdNodes = after.nodes.filter((n) => !beforeNodeById.has(n.id));
    const deletedNodes = before.nodes.filter((n) => !afterNodeById.has(n.id));
    const updatedNodes = after.nodes.filter((n) => {
        const prev = beforeNodeById.get(n.id);
        return prev !== undefined && JSON.stringify(prev) !== JSON.stringify(n);
    });

    const beforeConnById = new Map(before.connections.map((c) => [c.id, c]));
    const afterConnById = new Map(after.connections.map((c) => [c.id, c]));

    const createdConnections = after.connections.filter((c) => !beforeConnById.has(c.id));
    const deletedConnections = before.connections.filter((c) => !afterConnById.has(c.id));

    return { createdNodes, updatedNodes, deletedNodes, createdConnections, deletedConnections };
}
