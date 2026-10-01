import { NodeType } from '@shared/models';
import { generateUuid } from '@shared/utils';

import { generatePortsForNode, parsePortId } from '../../core/helpers/helpers';
import { ConnectionModel } from '../../core/models/connection.model';
import { FlowModel } from '../../core/models/flow.model';
import { NodeModel } from '../../core/models/node.model';
import { CustomPortId } from '../../core/models/port.model';
import { createFlowConnection } from '../connection.factory';
import { getInputPortRole } from '../node-port-roles';

export function unpackSubflow(parentFlow: FlowModel, subGraphNodeId: string, subflowModel: FlowModel): FlowModel {
    const subGraphNode = parentFlow.nodes.find((node) => node.id === subGraphNodeId);
    if (!subGraphNode) {
        throw new Error(`SubGraphNode with id "${subGraphNodeId}" not found in parent flow`);
    }

    if (subGraphNode.type !== NodeType.SUBGRAPH) {
        throw new Error(`Node "${subGraphNodeId}" is not a SubGraphNode (type: ${subGraphNode.type})`);
    }

    const filteredSubflowNodes = subflowModel.nodes.filter(
        (node) => node.type !== NodeType.START && node.type !== NodeType.END
    );

    const startNode = subflowModel.nodes.find((node) => node.type === NodeType.START);

    const existingNames = new Set(
        parentFlow.nodes.filter((node) => node.id !== subGraphNodeId).map((node) => node.node_name)
    );

    const oldIdToNewId = buildIdMap(filteredSubflowNodes);

    const copiedNodes = cloneNodesWithFreshIds(filteredSubflowNodes, oldIdToNewId, existingNames);

    const copiedConnections = remapInternalConnections(subflowModel.connections, oldIdToNewId);

    const entryPointNodeIds = detectEntryPointNodes(startNode, subflowModel.connections);

    const inboundConnections = parentFlow.connections.filter(
        (connection) => connection.targetNodeId === subGraphNodeId
    );
    const outboundConnections = parentFlow.connections.filter(
        (connection) => connection.sourceNodeId === subGraphNodeId
    );
    const subGraphNodeConnectionIds = new Set([
        ...inboundConnections.map((connection) => connection.id),
        ...outboundConnections.map((connection) => connection.id),
    ]);

    const rewiredConnections = rewireInboundEdges(inboundConnections, entryPointNodeIds, oldIdToNewId, copiedNodes);

    mergeInputMaps(subGraphNode, copiedNodes, entryPointNodeIds, oldIdToNewId);

    const remainingParentNodes = parentFlow.nodes.filter((node) => node.id !== subGraphNodeId);
    const remainingParentConnections = parentFlow.connections.filter(
        (connection) => !subGraphNodeConnectionIds.has(connection.id)
    );

    const firstNewEntryId = resolveFirstEntryPointId(entryPointNodeIds, oldIdToNewId);
    const updatedParentNodes = redirectParentDecisionTableRefs(remainingParentNodes, subGraphNodeId, firstNewEntryId);

    return {
        nodes: [...updatedParentNodes, ...copiedNodes],
        connections: [...remainingParentConnections, ...copiedConnections, ...rewiredConnections],
    };
}

function buildIdMap(nodes: NodeModel[]): Map<string, string> {
    const map = new Map<string, string>();
    for (const node of nodes) {
        map.set(node.id, generateUuid());
    }
    return map;
}

function resolveUniqueName(baseName: string, existingNames: Set<string>): string {
    if (!existingNames.has(baseName)) {
        return baseName;
    }

    let suffix = 2;
    while (existingNames.has(`${baseName} (${suffix})`)) {
        suffix++;
    }
    return `${baseName} (${suffix})`;
}

function cloneNodesWithFreshIds(
    nodes: NodeModel[],
    oldIdToNewId: Map<string, string>,
    existingNames: Set<string>
): NodeModel[] {
    return nodes.map((node) => {
        const newId = oldIdToNewId.get(node.id)!;
        const clonedData = node.data ? JSON.parse(JSON.stringify(node.data)) : node.data;

        if (isDecisionTableType(node.type) && clonedData) {
            remapDecisionTableNodeRefs(clonedData, oldIdToNewId);
        }

        const clonedInputMap = node.input_map ? JSON.parse(JSON.stringify(node.input_map)) : {};
        const newPorts = generatePortsForNode(newId, node.type, clonedData);

        const resolvedName = resolveUniqueName(node.node_name, existingNames);
        existingNames.add(resolvedName);

        return {
            ...node,
            id: newId,
            backendId: null,
            node_name: resolvedName,
            data: clonedData,
            input_map: clonedInputMap,
            ports: newPorts,
            position: { ...node.position },
            size: { ...node.size },
        } as NodeModel;
    });
}

function isDecisionTableType(type: NodeType): boolean {
    return type === NodeType.TABLE || type === NodeType.CLASSIFICATION_TABLE;
}

function remapDecisionTableNodeRefs(data: Record<string, unknown>, oldIdToNewId: Map<string, string>): void {
    const table = data['table'] as Record<string, unknown> | undefined;
    if (!table) return;

    table['default_next_node'] = remapNodeRef(table['default_next_node'] as string | null, oldIdToNewId);
    table['next_error_node'] = remapNodeRef(table['next_error_node'] as string | null, oldIdToNewId);

    const conditionGroups = table['condition_groups'] as Array<Record<string, unknown>> | undefined;
    if (Array.isArray(conditionGroups)) {
        for (const group of conditionGroups) {
            group['next_node'] = remapNodeRef(group['next_node'] as string | null, oldIdToNewId);
        }
    }
}

function remapNodeRef(ref: string | null, oldIdToNewId: Map<string, string>): string | null {
    if (!ref) return null;
    return oldIdToNewId.get(ref) ?? null;
}

function extractPortRole(portId: CustomPortId): string | null {
    const parsed = parsePortId(portId);
    return parsed?.portRole ?? null;
}

function remapInternalConnections(
    connections: ConnectionModel[],
    oldIdToNewId: Map<string, string>
): ConnectionModel[] {
    const result: ConnectionModel[] = [];

    for (const connection of connections) {
        const newSourceNodeId = oldIdToNewId.get(connection.sourceNodeId);
        const newTargetNodeId = oldIdToNewId.get(connection.targetNodeId);
        if (!newSourceNodeId || !newTargetNodeId) continue;

        const sourcePortRole = extractPortRole(connection.sourcePortId);
        const targetPortRole = extractPortRole(connection.targetPortId);
        if (!sourcePortRole || !targetPortRole) continue;

        const newSourcePortId = `${newSourceNodeId}_${sourcePortRole}` as CustomPortId;
        const newTargetPortId = `${newTargetNodeId}_${targetPortRole}` as CustomPortId;

        result.push({
            ...connection,
            id: `${newSourcePortId}+${newTargetPortId}`,
            sourceNodeId: newSourceNodeId,
            targetNodeId: newTargetNodeId,
            sourcePortId: newSourcePortId,
            targetPortId: newTargetPortId,
            data: null,
        });
    }

    return result;
}

function detectEntryPointNodes(startNode: NodeModel | undefined, subflowConnections: ConnectionModel[]): Set<string> {
    if (!startNode) {
        return new Set<string>();
    }

    const entryPointIds = new Set<string>();
    for (const connection of subflowConnections) {
        if (connection.sourceNodeId === startNode.id) {
            entryPointIds.add(connection.targetNodeId);
        }
    }
    return entryPointIds;
}

function rewireInboundEdges(
    inboundConnections: ConnectionModel[],
    entryPointNodeIds: Set<string>,
    oldIdToNewId: Map<string, string>,
    copiedNodes: NodeModel[]
): ConnectionModel[] {
    const rewiredConnections: ConnectionModel[] = [];

    for (const connection of inboundConnections) {
        for (const originalEntryId of entryPointNodeIds) {
            const newEntryId = oldIdToNewId.get(originalEntryId);
            if (!newEntryId) continue;

            const targetNode = copiedNodes.find((node) => node.id === newEntryId);
            if (!targetNode) continue;

            const inputRole = getInputPortRole(targetNode.type);
            const targetPortId = `${newEntryId}_${inputRole}` as CustomPortId;

            rewiredConnections.push(
                createFlowConnection(connection.sourceNodeId, newEntryId, connection.sourcePortId, targetPortId)
            );
        }
    }

    return rewiredConnections;
}

function resolveFirstEntryPointId(entryPointNodeIds: Set<string>, oldIdToNewId: Map<string, string>): string | null {
    for (const originalId of entryPointNodeIds) {
        const newId = oldIdToNewId.get(originalId);
        if (newId) return newId;
    }
    return null;
}

function redirectParentDecisionTableRefs(
    nodes: NodeModel[],
    subGraphNodeId: string,
    replacementId: string | null
): NodeModel[] {
    return nodes.map((node) => {
        if (!isDecisionTableType(node.type) || !node.data) return node;

        const clonedData = JSON.parse(JSON.stringify(node.data));
        const table = clonedData['table'] as Record<string, unknown> | undefined;
        if (!table) return node;

        let changed = false;

        changed = redirectRef(table, 'default_next_node', subGraphNodeId, replacementId) || changed;
        changed = redirectRef(table, 'next_error_node', subGraphNodeId, replacementId) || changed;

        const conditionGroups = table['condition_groups'] as Array<Record<string, unknown>> | undefined;
        if (Array.isArray(conditionGroups)) {
            for (const group of conditionGroups) {
                changed = redirectRef(group, 'next_node', subGraphNodeId, replacementId) || changed;
            }
        }

        return changed ? { ...node, data: clonedData } : node;
    });
}

function redirectRef(
    obj: Record<string, unknown>,
    field: string,
    subGraphNodeId: string,
    replacementId: string | null
): boolean {
    const ref = obj[field] as string | null;
    if (ref === subGraphNodeId) {
        obj[field] = replacementId;
        return true;
    }
    return false;
}

function mergeInputMaps(
    subGraphNode: NodeModel,
    copiedNodes: NodeModel[],
    entryPointNodeIds: Set<string>,
    oldIdToNewId: Map<string, string>
): void {
    if (!subGraphNode.input_map || Object.keys(subGraphNode.input_map).length === 0) {
        return;
    }

    for (const originalEntryId of entryPointNodeIds) {
        const newEntryId = oldIdToNewId.get(originalEntryId);
        if (!newEntryId) continue;

        const copiedNode = copiedNodes.find((node) => node.id === newEntryId);
        if (!copiedNode) continue;

        const existingValues = new Set(Object.values(copiedNode.input_map));

        for (const [key, value] of Object.entries(subGraphNode.input_map)) {
            if (!(key in copiedNode.input_map) && !existingValues.has(value)) {
                copiedNode.input_map[key] = value;
            }
        }
    }
}
