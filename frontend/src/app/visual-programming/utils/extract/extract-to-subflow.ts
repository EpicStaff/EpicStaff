import { NODE_COLORS, NODE_ICONS, NodeType } from '@shared/models';
import { generateUuid } from '@shared/utils';

import { generatePortsForNode, parsePortId } from '../../core/helpers/helpers';
import { getDefaultNodeSize } from '../../core/helpers/node-size.util';
import { ConnectionModel } from '../../core/models/connection.model';
import { FlowModel } from '../../core/models/flow.model';
import { NodeModel, SubGraphNodeModel } from '../../core/models/node.model';
import { CustomPortId } from '../../core/models/port.model';
import { createFlowConnection } from '../connection.factory';
import { getInputPortRole, getOutputPortRole } from '../node-port-roles';

export interface ExtractionResult {
    subflowModel: FlowModel;
    parentModel: FlowModel;
    subGraphNodeInputMap: Record<string, unknown>;
}

const START_NODE_HORIZONTAL_OFFSET = 200;

export function extractToSubflow(
    parentFlow: FlowModel,
    selectedNodeIds: Set<string>,
    subGraphNodeId: string,
    subflowGraphId: number
): ExtractionResult {
    const effectiveSelection = new Set(selectedNodeIds);
    for (const node of parentFlow.nodes) {
        if (node.type === NodeType.START && effectiveSelection.has(node.id)) {
            effectiveSelection.delete(node.id);
        }
    }

    const selectedNodes = parentFlow.nodes.filter((node) => effectiveSelection.has(node.id));
    const unselectedNodes = parentFlow.nodes.filter((node) => !effectiveSelection.has(node.id));

    const { internal, inbound, external } = classifyConnections(parentFlow.connections, effectiveSelection);

    const oldIdToNewId = buildIdMap(selectedNodes);
    const subflowNodes = cloneNodesWithFreshIds(selectedNodes, oldIdToNewId);
    const subflowInternalConnections = remapConnections(internal, oldIdToNewId);

    const entryPointNodeIds = detectEntryPointNodes(effectiveSelection, internal, inbound);
    const startNode = createSubflowStartNode(selectedNodes, entryPointNodeIds);
    const startNodePorts = generatePortsForNode(startNode.id, NodeType.START);
    const startNodeWithPorts: NodeModel = { ...startNode, ports: startNodePorts };

    const startToEntryConnections = createStartToEntryConnections(
        startNode.id,
        entryPointNodeIds,
        oldIdToNewId,
        subflowNodes
    );

    const subflowModel: FlowModel = {
        nodes: [startNodeWithPorts, ...subflowNodes],
        connections: [...subflowInternalConnections, ...startToEntryConnections],
    };

    const subGraphNodeInputMap = buildSubGraphNodeInputMap(selectedNodes);

    const subGraphNode = createSubGraphNode(subGraphNodeId, subflowGraphId, selectedNodes, subGraphNodeInputMap);

    const reconnectedInboundConnections = reconnectInboundEdges(inbound, subGraphNode);

    const parentModel: FlowModel = {
        nodes: [...unselectedNodes, subGraphNode],
        connections: [...external, ...reconnectedInboundConnections],
    };

    return { subflowModel, parentModel, subGraphNodeInputMap };
}

interface ClassifiedConnections {
    internal: ConnectionModel[];
    inbound: ConnectionModel[];
    outbound: ConnectionModel[];
    external: ConnectionModel[];
}

function classifyConnections(connections: ConnectionModel[], selectedIds: Set<string>): ClassifiedConnections {
    const internal: ConnectionModel[] = [];
    const inbound: ConnectionModel[] = [];
    const outbound: ConnectionModel[] = [];
    const external: ConnectionModel[] = [];

    for (const connection of connections) {
        const sourceInSelection = selectedIds.has(connection.sourceNodeId);
        const targetInSelection = selectedIds.has(connection.targetNodeId);

        if (sourceInSelection && targetInSelection) {
            internal.push(connection);
        } else if (!sourceInSelection && targetInSelection) {
            inbound.push(connection);
        } else if (sourceInSelection && !targetInSelection) {
            outbound.push(connection);
        } else {
            external.push(connection);
        }
    }

    return { internal, inbound, outbound, external };
}

function buildIdMap(nodes: NodeModel[]): Map<string, string> {
    const map = new Map<string, string>();
    for (const node of nodes) {
        map.set(node.id, generateUuid());
    }
    return map;
}

function cloneNodesWithFreshIds(nodes: NodeModel[], oldIdToNewId: Map<string, string>): NodeModel[] {
    return nodes.map((node) => {
        const newId = oldIdToNewId.get(node.id)!;
        const clonedData = node.data ? JSON.parse(JSON.stringify(node.data)) : node.data;
        const clonedInputMap = node.input_map ? JSON.parse(JSON.stringify(node.input_map)) : {};
        const newPorts = generatePortsForNode(newId, node.type, clonedData);

        return {
            ...node,
            id: newId,
            backendId: null,
            data: clonedData,
            input_map: clonedInputMap,
            ports: newPorts,
            position: { ...node.position },
            size: { ...node.size },
        } as NodeModel;
    });
}

function remapConnections(connections: ConnectionModel[], oldIdToNewId: Map<string, string>): ConnectionModel[] {
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

function extractPortRole(portId: CustomPortId): string | null {
    const parsed = parsePortId(portId);
    return parsed?.portRole ?? null;
}

function detectEntryPointNodes(
    selectedIds: Set<string>,
    internalConnections: ConnectionModel[],
    inboundConnections: ConnectionModel[]
): Set<string> {
    const nodesWithInboundFromOutside = new Set(inboundConnections.map((connection) => connection.targetNodeId));

    const nodesWithInternalInbound = new Set(internalConnections.map((connection) => connection.targetNodeId));

    const entryPoints = new Set<string>();

    for (const nodeId of selectedIds) {
        if (nodesWithInboundFromOutside.has(nodeId) || !nodesWithInternalInbound.has(nodeId)) {
            entryPoints.add(nodeId);
        }
    }

    return entryPoints;
}

function createSubflowStartNode(selectedNodes: NodeModel[], entryPointNodeIds: Set<string>): NodeModel {
    const entryNodes = selectedNodes.filter((node) => entryPointNodeIds.has(node.id));
    const referenceNodes = entryNodes.length > 0 ? entryNodes : selectedNodes;

    const leftmostX = Math.min(...referenceNodes.map((node) => node.position.x));
    const averageY = referenceNodes.reduce((sum, node) => sum + node.position.y, 0) / referenceNodes.length;

    return {
        id: generateUuid(),
        backendId: null,
        type: NodeType.START,
        node_name: '__start__',
        data: { initialState: {} },
        position: { x: leftmostX - START_NODE_HORIZONTAL_OFFSET, y: averageY },
        ports: null,
        color: NODE_COLORS[NodeType.START],
        icon: NODE_ICONS[NodeType.START],
        input_map: {},
        output_variable_path: null,
        size: getDefaultNodeSize(NodeType.START),
    };
}

function createStartToEntryConnections(
    startNodeId: string,
    entryPointNodeIds: Set<string>,
    oldIdToNewId: Map<string, string>,
    subflowNodes: NodeModel[]
): ConnectionModel[] {
    const startOutputRole = getOutputPortRole(NodeType.START);
    const startPortId = `${startNodeId}_${startOutputRole}` as CustomPortId;

    const connections: ConnectionModel[] = [];

    for (const originalNodeId of entryPointNodeIds) {
        const newNodeId = oldIdToNewId.get(originalNodeId);
        if (!newNodeId) continue;

        const targetNode = subflowNodes.find((node) => node.id === newNodeId);
        if (!targetNode) continue;

        const inputRole = getInputPortRole(targetNode.type);
        const targetPortId = `${newNodeId}_${inputRole}` as CustomPortId;

        connections.push(createFlowConnection(startNodeId, newNodeId, startPortId, targetPortId));
    }

    return connections;
}

const VARIABLES_PREFIX = 'variables.';

function collectInternalVariablePaths(nodes: NodeModel[]): Set<string> {
    const paths = new Set<string>();
    for (const node of nodes) {
        if (node.output_variable_path && typeof node.output_variable_path === 'string') {
            paths.add(node.output_variable_path);
        }
    }
    return paths;
}

function extractVariableName(variablePath: string): string | null {
    if (typeof variablePath !== 'string' || !variablePath.startsWith(VARIABLES_PREFIX)) {
        return null;
    }
    const name = variablePath.slice(VARIABLES_PREFIX.length);
    const dotIndex = name.indexOf('.');
    return dotIndex === -1 ? name : name.slice(0, dotIndex);
}

function buildSubGraphNodeInputMap(selectedNodes: NodeModel[]): Record<string, unknown> {
    const internalPaths = collectInternalVariablePaths(selectedNodes);
    const merged: Record<string, unknown> = {};

    for (const node of selectedNodes) {
        if (!node.input_map) continue;

        for (const [, value] of Object.entries(node.input_map)) {
            if (typeof value !== 'string') continue;
            if (internalPaths.has(value)) continue;

            const variableName = extractVariableName(value);
            if (!variableName) continue;

            merged[variableName] = value;
        }
    }

    return merged;
}

function createSubGraphNode(
    nodeId: string,
    subflowGraphId: number,
    selectedNodes: NodeModel[],
    inputMap: Record<string, unknown>
): SubGraphNodeModel {
    const centroidX = selectedNodes.reduce((sum, node) => sum + node.position.x, 0) / selectedNodes.length;
    const centroidY = selectedNodes.reduce((sum, node) => sum + node.position.y, 0) / selectedNodes.length;

    const ports = generatePortsForNode(nodeId, NodeType.SUBGRAPH);

    return {
        id: nodeId,
        backendId: null,
        type: NodeType.SUBGRAPH,
        node_name: '',
        data: {
            id: subflowGraphId,
            uuid: '',
            name: '',
            description: '',
        },
        position: { x: centroidX, y: centroidY },
        ports,
        color: NODE_COLORS[NodeType.SUBGRAPH],
        icon: NODE_ICONS[NodeType.SUBGRAPH],
        input_map: inputMap,
        output_variable_path: null,
        size: getDefaultNodeSize(NodeType.SUBGRAPH),
    };
}

function reconnectInboundEdges(
    inboundConnections: ConnectionModel[],
    subGraphNode: SubGraphNodeModel
): ConnectionModel[] {
    const inputRole = getInputPortRole(NodeType.SUBGRAPH);
    const subGraphInputPortId = `${subGraphNode.id}_${inputRole}` as CustomPortId;

    return inboundConnections.map((connection) => {
        const newConnectionId = `${connection.sourcePortId}+${subGraphInputPortId}`;
        return {
            ...connection,
            id: newConnectionId,
            targetNodeId: subGraphNode.id,
            targetPortId: subGraphInputPortId,
            data: null,
        };
    });
}
