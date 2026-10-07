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

    const entryPointNodeIds = detectEntryPointNodes(inbound);
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

    const subGraphNodeInputMap = buildSubGraphNodeInputMap(selectedNodes, unselectedNodes, parentFlow.nodes);

    const subGraphNode = createSubGraphNode(subGraphNodeId, subflowGraphId, selectedNodes, subGraphNodeInputMap);

    const reconnectedInboundConnections = reconnectInboundEdges(inbound, subGraphNode);

    const updatedUnselectedNodes = redirectParentDecisionTableRefs(unselectedNodes, effectiveSelection, subGraphNodeId);

    const parentModel: FlowModel = {
        nodes: [...updatedUnselectedNodes, subGraphNode],
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

        if (isDecisionTableType(node.type) && clonedData) {
            remapDecisionTableNodeRefs(clonedData, oldIdToNewId);
        }

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

function redirectParentDecisionTableRefs(
    unselectedNodes: NodeModel[],
    extractedIds: Set<string>,
    subGraphNodeId: string
): NodeModel[] {
    return unselectedNodes.map((node) => {
        if (!isDecisionTableType(node.type) || !node.data) return node;

        const clonedData = JSON.parse(JSON.stringify(node.data));
        const table = clonedData['table'] as Record<string, unknown> | undefined;
        if (!table) return node;

        let changed = false;

        changed = redirectRef(table, 'default_next_node', extractedIds, subGraphNodeId) || changed;
        changed = redirectRef(table, 'next_error_node', extractedIds, subGraphNodeId) || changed;

        const conditionGroups = table['condition_groups'] as Array<Record<string, unknown>> | undefined;
        if (Array.isArray(conditionGroups)) {
            for (const group of conditionGroups) {
                changed = redirectRef(group, 'next_node', extractedIds, subGraphNodeId) || changed;
            }
        }

        return changed ? { ...node, data: clonedData } : node;
    });
}

function redirectRef(
    obj: Record<string, unknown>,
    field: string,
    extractedIds: Set<string>,
    replacementId: string
): boolean {
    const ref = obj[field] as string | null;
    if (ref && extractedIds.has(ref)) {
        obj[field] = replacementId;
        return true;
    }
    return false;
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

function detectEntryPointNodes(inboundConnections: ConnectionModel[]): Set<string> {
    return new Set(inboundConnections.map((connection) => connection.targetNodeId));
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
const VARIABLES_REGEX = /\bvariables\.([A-Za-z_][A-Za-z0-9_]*)/g;
const BARE_IDENTIFIER_CHAIN_REGEX = /\b([A-Za-z_][A-Za-z0-9_]*)(?:\.[A-Za-z0-9_]+)*/g;

/**
 * Python keywords, builtins, and CDT wrapper-injected names that should never
 * be treated as flow variable references when scanning bare identifiers.
 */
const PYTHON_EXCLUDED_IDENTIFIERS = new Set([
    // Python keywords
    'and',
    'as',
    'assert',
    'async',
    'await',
    'break',
    'class',
    'continue',
    'def',
    'del',
    'elif',
    'else',
    'except',
    'finally',
    'for',
    'from',
    'global',
    'if',
    'import',
    'in',
    'is',
    'lambda',
    'nonlocal',
    'not',
    'or',
    'pass',
    'raise',
    'return',
    'try',
    'while',
    'with',
    'yield',
    // Python builtins
    'True',
    'False',
    'None',
    'print',
    'len',
    'str',
    'int',
    'float',
    'bool',
    'list',
    'dict',
    'tuple',
    'set',
    'type',
    'range',
    'enumerate',
    'zip',
    'map',
    'filter',
    'sorted',
    'reversed',
    'min',
    'max',
    'sum',
    'abs',
    'round',
    'any',
    'all',
    'isinstance',
    'issubclass',
    'hasattr',
    'getattr',
    'setattr',
    'delattr',
    'callable',
    'repr',
    'format',
    'id',
    'hash',
    'input',
    'open',
    'super',
    'object',
    'property',
    'staticmethod',
    'classmethod',
    // CDT wrapper-injected names
    'variables',
    'result',
    '_raw',
    '_to_ns',
    'kwargs',
    'main',
]);

function extractVariableName(variablePath: string): string | null {
    if (typeof variablePath !== 'string' || !variablePath.startsWith(VARIABLES_PREFIX)) {
        return null;
    }
    const name = variablePath.slice(VARIABLES_PREFIX.length);
    const dotIndex = name.indexOf('.');
    return dotIndex === -1 ? name : name.slice(0, dotIndex);
}

function extractVariableNamesFromCode(code: string): string[] {
    const seen = new Set<string>();

    // Pass 1: explicit `variables.name` references (always reliable)
    let match: RegExpExecArray | null;
    VARIABLES_REGEX.lastIndex = 0;
    while ((match = VARIABLES_REGEX.exec(code)) !== null) {
        seen.add(match[1]);
    }

    // Pass 2: bare identifiers — catches CDT expressions
    // that the backend resolves without the `variables.` prefix.
    // False positives are harmless (unused input_map entries are ignored at runtime);
    // false negatives (missing a variable) would break the subflow.
    BARE_IDENTIFIER_CHAIN_REGEX.lastIndex = 0;
    while ((match = BARE_IDENTIFIER_CHAIN_REGEX.exec(code)) !== null) {
        const identifier = match[1];
        if (!PYTHON_EXCLUDED_IDENTIFIERS.has(identifier)) {
            seen.add(identifier);
        }
    }

    return Array.from(seen);
}

function addVariable(merged: Record<string, unknown>, variableName: string): void {
    if (variableName in merged) return;
    merged[variableName] = `${VARIABLES_PREFIX}${variableName}`;
}

function collectInputMapVariables(inputMap: Record<string, unknown>, merged: Record<string, unknown>): void {
    for (const value of Object.values(inputMap)) {
        if (typeof value !== 'string') continue;
        const variableName = extractVariableName(value);
        if (variableName) {
            addVariable(merged, variableName);
        }
    }
}

function collectCdtVariables(node: NodeModel, merged: Record<string, unknown>): void {
    if (!isDecisionTableType(node.type) || !node.data) return;

    const data = node.data as Record<string, unknown>;
    const table = data['table'] as Record<string, unknown> | undefined;
    if (!table) return;

    const preComp = table['pre_computation'] as Record<string, unknown> | undefined;
    const preInputMap = (preComp?.['input_map'] ?? table['pre_input_map']) as Record<string, string> | undefined;
    if (preInputMap && typeof preInputMap === 'object') {
        collectInputMapVariables(preInputMap, merged);
    }

    const postComp = table['post_computation'] as Record<string, unknown> | undefined;
    const postInputMap = (postComp?.['input_map'] ?? table['post_input_map']) as Record<string, string> | undefined;
    if (postInputMap && typeof postInputMap === 'object') {
        collectInputMapVariables(postInputMap, merged);
    }

    const conditionGroups = table['condition_groups'] as Array<Record<string, unknown>> | undefined;
    if (!Array.isArray(conditionGroups)) return;

    for (const group of conditionGroups) {
        const expression = group['expression'] as string | null;
        if (expression) {
            for (const name of extractVariableNamesFromCode(expression)) {
                addVariable(merged, name);
            }
        }

        const manipulation = group['manipulation'] as string | null;
        if (manipulation) {
            for (const name of extractVariableNamesFromCode(manipulation)) {
                addVariable(merged, name);
            }
        }

        const fieldExpressions = group['field_expressions'] as Record<string, string> | undefined;
        if (fieldExpressions && typeof fieldExpressions === 'object') {
            for (const varName of Object.keys(fieldExpressions)) {
                addVariable(merged, varName);
            }
        }

        const fieldManipulations = group['field_manipulations'] as Record<string, string> | undefined;
        if (fieldManipulations && typeof fieldManipulations === 'object') {
            for (const varName of Object.keys(fieldManipulations)) {
                addVariable(merged, varName);
            }
        }
    }
}

function collectProducedVariableNames(nodes: NodeModel[]): Set<string> {
    const names = new Set<string>();
    for (const node of nodes) {
        if (node.output_variable_path) {
            const name = extractVariableName(node.output_variable_path);
            if (name) names.add(name);
        }

        if (isDecisionTableType(node.type) && node.data) {
            const data = node.data as Record<string, unknown>;
            const table = data['table'] as Record<string, unknown> | undefined;
            if (table) {
                const preComp = table['pre_computation'] as Record<string, unknown> | undefined;
                const preOutputPath = (preComp?.['output_variable_path'] ?? table['pre_output_variable_path']) as
                    | string
                    | undefined;
                if (preOutputPath) {
                    const name = extractVariableName(preOutputPath);
                    if (name) names.add(name);
                }

                const postComp = table['post_computation'] as Record<string, unknown> | undefined;
                const postOutputPath = (postComp?.['output_variable_path'] ?? table['post_output_variable_path']) as
                    | string
                    | undefined;
                if (postOutputPath) {
                    const name = extractVariableName(postOutputPath);
                    if (name) names.add(name);
                }
            }
        }
    }
    return names;
}

function collectStartNodeVariableNames(parentNodes: NodeModel[]): Set<string> {
    const startNode = parentNodes.find((node) => node.type === NodeType.START);
    if (!startNode?.data) return new Set();
    const initialState = (startNode.data as unknown as Record<string, unknown>)['initialState'];
    if (!initialState || typeof initialState !== 'object') return new Set();

    const variables = (initialState as Record<string, unknown>)['variables'];
    if (variables && typeof variables === 'object') {
        return new Set(Object.keys(variables as Record<string, unknown>));
    }

    return new Set(Object.keys(initialState as Record<string, unknown>));
}

function buildSubGraphNodeInputMap(
    selectedNodes: NodeModel[],
    unselectedNodes: NodeModel[],
    parentNodes: NodeModel[]
): Record<string, unknown> {
    const merged: Record<string, unknown> = {};

    for (const node of selectedNodes) {
        if (node.input_map) {
            collectInputMapVariables(node.input_map, merged);
        }
        collectCdtVariables(node, merged);
    }

    const internallyProduced = collectProducedVariableNames(selectedNodes);
    const externallyProduced = collectProducedVariableNames(unselectedNodes);
    const startVariables = collectStartNodeVariableNames(parentNodes);

    for (const name of Object.keys(merged)) {
        if (internallyProduced.has(name) && !startVariables.has(name) && !externallyProduced.has(name)) {
            delete merged[name];
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
        output_variable_path: 'variables',
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
