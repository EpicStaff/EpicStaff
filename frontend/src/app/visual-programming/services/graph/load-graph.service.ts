/**
 * Pure functions to build a FlowModel from a GraphDto.
 *
 * Instead of blindly taking `graph.metadata` as the entire UI state,
 * these functions reconstruct the node list and connections from the
 * individual backend node/edge lists.  UI-only metadata (position,
 * color, icon, size, backgroundColor) is read from each node's `metadata`
 * JSON field.  All node types including notes are now backend-managed.
 */

import { v4 as uuidv4 } from 'uuid';

import { GraphDto } from '../../../features/flows/models/graph.model';
import { FlowModel } from '../../core/models/flow.model';
import { NodeType } from '../../core/enums/node-type';
import { NODE_COLORS, NODE_ICONS } from '../../core/enums/node-config';
import { ConnectionModel } from '../../core/models/connection.model';
import { CustomPortId } from '../../core/models/port.model';
import {
    NodeModel,
    StartNodeModel,
    ProjectNodeModel,
    PythonNodeModel,
    LLMNodeModel,
    FileExtractorNodeModel,
    AudioToTextNodeModel,
    SubGraphNodeModel,
    WebhookTriggerNodeModel,
    TelegramTriggerNodeModel,
    EndNodeModel,
    EdgeNodeModel,
    DecisionTableNodeModel,
    NoteNodeModel,
} from '../../core/models/node.model';

import { CrewNode } from '../../../pages/flows-page/components/flow-visual-programming/models/crew-node.model';
import { PythonNode } from '../../../pages/flows-page/components/flow-visual-programming/models/python-node.model';
import { GetLLMNodeRequest } from '../../../pages/flows-page/components/flow-visual-programming/models/llm-node.model';
import { GetFileExtractorNodeRequest } from '../../../pages/flows-page/components/flow-visual-programming/models/file-extractor.model';
import { GetAudioToTextNodeRequest } from '../../../pages/flows-page/components/flow-visual-programming/models/audio-to-text.model';
import { SubGraphNode } from '../../../pages/flows-page/components/flow-visual-programming/models/subgraph-node.model';
import { GetWebhookTriggerNodeRequest } from '../../../pages/flows-page/components/flow-visual-programming/models/webhook-trigger';
import { GetTelegramTriggerNodeRequest } from '../../../pages/flows-page/components/flow-visual-programming/models/telegram-trigger.model';
import { ConditionalEdge } from '../../../pages/flows-page/components/flow-visual-programming/models/conditional-edge.model';
import { Edge } from '../../../pages/flows-page/components/flow-visual-programming/models/edge.model';
import { StartNode } from '../../../pages/flows-page/components/flow-visual-programming/models/start-node.model';
import { EndNode } from '../../../pages/flows-page/components/flow-visual-programming/models/end-node.model';
import { GetDecisionTableNodeRequest } from '../../../pages/flows-page/components/flow-visual-programming/models/decision-table-node.model';
import { NoteNode } from '../../../pages/flows-page/components/flow-visual-programming/models/note-node.model';

import { NodeUIMetadata } from './save-graph.types';

// ─────────────────────────────────────────────────────────────────────────────
// Helpers
// ─────────────────────────────────────────────────────────────────────────────

/** Read UI metadata from a backend node's `metadata` field (with defaults). */
function readUIMetadata(
    metadata: Record<string, any> | undefined | null,
    nodeType: NodeType,
    fallbackIndex: number
): NodeUIMetadata {
    const m = metadata ?? {};
    return {
        position: m['position'] ?? { x: 100 + (fallbackIndex % 5) * 400, y: 100 + Math.floor(fallbackIndex / 5) * 200 },
        color: m['color'] ?? NODE_COLORS[nodeType] ?? '#685fff',
        icon: m['icon'] ?? NODE_ICONS[nodeType] ?? 'ti ti-code',
        size: m['size'] ?? getDefaultSize(nodeType),
        parentId: null,
    };
}

function getDefaultSize(nodeType: NodeType): { width: number; height: number } {
    switch (nodeType) {
        case NodeType.START:
            return { width: 125, height: 60 };
        case NodeType.NOTE:
            return { width: 200, height: 150 };
        case NodeType.TABLE:
            return { width: 330, height: 152 };
        default:
            return { width: 330, height: 60 };
    }
}

/** Build a connection model between two node UUIDs. */
function makeConnection(
    sourceNodeId: string,
    targetNodeId: string,
    sourcePortId: CustomPortId,
    targetPortId: CustomPortId,
    startColor?: string,
    endColor?: string
): ConnectionModel {
    return {
        id: uuidv4(),
        category: 'default',
        sourceNodeId,
        targetNodeId,
        sourcePortId,
        targetPortId,
        startColor,
        endColor,
        behavior: 'fixed',
        type: 'segment',
    };
}

// ─────────────────────────────────────────────────────────────────────────────
// Node builders — each takes a backend DTO and returns a UI NodeModel
// ─────────────────────────────────────────────────────────────────────────────

function buildStartNode(sn: StartNode, idx: number): StartNodeModel {
    const ui = readUIMetadata(sn.metadata, NodeType.START, idx);
    return {
        id: uuidv4(),
        backendId: sn.id,
        category: 'web',
        type: NodeType.START,
        node_name: '__start__',
        data: { initialState: sn.variables ?? {} },
        position: ui.position,
        ports: null,
        parentId: null,
        color: ui.color,
        icon: ui.icon,
        input_map: {},
        output_variable_path: null,
        size: ui.size,
    };
}

function buildCrewNode(cn: CrewNode, idx: number): ProjectNodeModel {
    const ui = readUIMetadata(cn.metadata, NodeType.PROJECT, idx);
    return {
        id: uuidv4(),
        backendId: cn.id,
        category: 'web',
        type: NodeType.PROJECT,
        node_name: cn.node_name,
        data: cn.crew,
        position: ui.position,
        ports: null,
        parentId: null,
        color: ui.color,
        icon: ui.icon,
        input_map: cn.input_map ?? {},
        output_variable_path: cn.output_variable_path,
        size: ui.size,
    };
}

function buildPythonNode(pn: PythonNode, idx: number): PythonNodeModel {
    const ui = readUIMetadata(pn.metadata, NodeType.PYTHON, idx);
    return {
        id: uuidv4(),
        backendId: pn.id,
        category: 'web',
        type: NodeType.PYTHON,
        node_name: pn.node_name,
        data: {
            name: pn.node_name,
            libraries: pn.python_code.libraries,
            code: pn.python_code.code,
            entrypoint: pn.python_code.entrypoint,
        },
        position: ui.position,
        ports: null,
        parentId: null,
        color: ui.color,
        icon: ui.icon,
        input_map: pn.input_map ?? {},
        output_variable_path: pn.output_variable_path,
        size: ui.size,
    };
}

function buildLLMNode(ln: GetLLMNodeRequest, idx: number): LLMNodeModel {
    const ui = readUIMetadata(ln.metadata, NodeType.LLM, idx);
    // Use the nested llm_config_detail from the backend, fall back to a stub
    const configDetail = ln.llm_config_detail ?? {
        id: ln.llm_config,
        custom_name: ln.node_name,
        model: 0,
        api_key: '',
        temperature: null,
        top_p: null,
        stop: null,
        max_tokens: null,
        presence_penalty: null,
        frequency_penalty: null,
        logit_bias: null,
        response_format: null,
        seed: null,
        timeout: null,
        is_visible: true,
    };
    return {
        id: uuidv4(),
        backendId: ln.id,
        category: 'web',
        type: NodeType.LLM,
        node_name: ln.node_name,
        data: configDetail,
        position: ui.position,
        ports: null,
        parentId: null,
        color: ui.color,
        icon: ui.icon,
        input_map: ln.input_map ?? {},
        output_variable_path: ln.output_variable_path,
        size: ui.size,
    };
}

function buildFileExtractorNode(n: GetFileExtractorNodeRequest, idx: number): FileExtractorNodeModel {
    const ui = readUIMetadata(n.metadata, NodeType.FILE_EXTRACTOR, idx);
    return {
        id: uuidv4(),
        backendId: n.id,
        category: 'web',
        type: NodeType.FILE_EXTRACTOR,
        node_name: n.node_name,
        data: undefined,
        position: ui.position,
        ports: null,
        parentId: null,
        color: ui.color,
        icon: ui.icon,
        input_map: n.input_map ?? {},
        output_variable_path: n.output_variable_path,
        size: ui.size,
    };
}

function buildAudioToTextNode(n: GetAudioToTextNodeRequest, idx: number): AudioToTextNodeModel {
    const ui = readUIMetadata(n.metadata, NodeType.AUDIO_TO_TEXT, idx);
    return {
        id: uuidv4(),
        backendId: n.id,
        category: 'web',
        type: NodeType.AUDIO_TO_TEXT,
        node_name: n.node_name,
        data: undefined,
        position: ui.position,
        ports: null,
        parentId: null,
        color: ui.color,
        icon: ui.icon,
        input_map: n.input_map ?? {},
        output_variable_path: n.output_variable_path,
        size: ui.size,
    };
}

function buildSubGraphNode(sn: SubGraphNode, idx: number): SubGraphNodeModel {
    const ui = readUIMetadata(sn.metadata, NodeType.SUBGRAPH, idx);
    // Use the nested subgraph_detail from the backend, fall back to a stub
    const subgraphDetail = sn.subgraph_detail ?? {
        id: sn.subgraph,
        name: sn.node_name,
        description: '',
        tags: [],
    };
    return {
        id: uuidv4(),
        backendId: sn.id,
        category: 'web',
        type: NodeType.SUBGRAPH,
        node_name: sn.node_name,
        data: subgraphDetail,
        position: ui.position,
        ports: null,
        parentId: null,
        color: ui.color,
        icon: ui.icon,
        input_map: sn.input_map ?? {},
        output_variable_path: sn.output_variable_path,
        size: ui.size,
        isBlocked: false,
    };
}

function buildWebhookTriggerNode(wn: GetWebhookTriggerNodeRequest, idx: number): WebhookTriggerNodeModel {
    const ui = readUIMetadata(wn.metadata, NodeType.WEBHOOK_TRIGGER, idx);
    return {
        id: uuidv4(),
        backendId: wn.id,
        category: 'web',
        type: NodeType.WEBHOOK_TRIGGER,
        node_name: wn.node_name,
        data: {
            webhook_trigger: wn.webhook_trigger,
            python_code: {
                name: wn.node_name,
                libraries: wn.python_code.libraries,
                code: wn.python_code.code,
                entrypoint: wn.python_code.entrypoint,
            },
        },
        position: ui.position,
        ports: null,
        parentId: null,
        color: ui.color,
        icon: ui.icon,
        input_map: wn.input_map ?? {},
        output_variable_path: wn.output_variable_path,
        size: ui.size,
    };
}

function buildTelegramTriggerNode(tn: GetTelegramTriggerNodeRequest, idx: number): TelegramTriggerNodeModel {
    const ui = readUIMetadata(tn.metadata, NodeType.TELEGRAM_TRIGGER, idx);
    return {
        id: uuidv4(),
        backendId: tn.id,
        category: 'web',
        type: NodeType.TELEGRAM_TRIGGER,
        node_name: tn.node_name,
        data: {
            telegram_bot_api_key: tn.telegram_bot_api_key,
            webhook_trigger: tn.webhook_trigger,
            fields: tn.fields,
        },
        position: ui.position,
        ports: null,
        parentId: null,
        color: ui.color,
        icon: ui.icon,
        input_map: {} as Record<string, any>,
        output_variable_path: null,
        size: ui.size,
    };
}

function buildEndNode(en: EndNode, idx: number): EndNodeModel {
    const ui = readUIMetadata(en.metadata, NodeType.END, idx);
    return {
        id: uuidv4(),
        backendId: en.id,
        category: 'web',
        type: NodeType.END,
        node_name: en.node_name ?? '__end_node__',
        data: { output_map: en.output_map ?? {} },
        position: ui.position,
        ports: null,
        parentId: null,
        color: ui.color,
        icon: ui.icon,
        input_map: {},
        output_variable_path: null,
        size: ui.size,
    };
}

function buildNoteNode(nn: NoteNode, idx: number): NoteNodeModel {
    const ui = readUIMetadata(nn.metadata, NodeType.NOTE, idx);
    return {
        id: uuidv4(),
        backendId: nn.id,
        category: 'web',
        type: NodeType.NOTE,
        node_name: nn.node_name,
        data: {
            content: nn.content,
            backgroundColor: nn.metadata?.['backgroundColor'] ?? undefined,
        },
        position: ui.position,
        ports: null,
        parentId: null,
        color: ui.color,
        icon: ui.icon,
        input_map: {},
        output_variable_path: null,
        size: ui.size,
    };
}

function buildDecisionTableNode(dn: GetDecisionTableNodeRequest, idx: number): DecisionTableNodeModel {
    const ui = readUIMetadata(dn.metadata, NodeType.TABLE, idx);
    return {
        id: uuidv4(),
        backendId: dn.id,
        category: 'web',
        type: NodeType.TABLE,
        node_name: dn.node_name,
        data: {
            name: dn.node_name,
            table: {
                default_next_node: dn.default_next_node,
                next_error_node: dn.next_error_node,
                condition_groups: dn.condition_groups.map(g => ({
                    group_name: g.group_name,
                    group_type: g.group_type as 'simple' | 'complex',
                    expression: g.expression,
                    conditions: g.conditions.map(c => ({
                        condition_name: c.condition_name,
                        condition: c.condition,
                    })),
                    manipulation: g.manipulation,
                    next_node: g.next_node,
                    valid: true,
                    order: g.order,
                })),
            },
        },
        position: ui.position,
        ports: null,
        parentId: null,
        color: ui.color,
        icon: ui.icon,
        input_map: {} as Record<string, any>,
        output_variable_path: null,
        size: ui.size,
    };
}

function buildConditionalEdgeNode(ce: ConditionalEdge, idx: number): EdgeNodeModel {
    const ui = readUIMetadata(ce.metadata, NodeType.EDGE, idx);
    return {
        id: uuidv4(),
        backendId: ce.id,
        category: 'web',
        type: NodeType.EDGE,
        node_name: (ce.metadata as any)?.['node_name'] || (ce.source + '_edge'),
        data: {
            source: ce.source,
            then: ce.then,
            python_code: {
                name: ce.source + '_edge',
                libraries: ce.python_code.libraries,
                code: ce.python_code.code,
                entrypoint: ce.python_code.entrypoint,
            },
            input_map: ce.input_map ?? {},
        },
        position: ui.position,
        ports: null,
        parentId: null,
        color: ui.color,
        icon: ui.icon,
        input_map: ce.input_map ?? {},
        output_variable_path: null,
        size: ui.size,
    };
}

// ─────────────────────────────────────────────────────────────────────────────
// Connection builders
// ─────────────────────────────────────────────────────────────────────────────

/**
 * Maps node_name → generated UUID for lookup when building connections.
 */
function buildNameToIdMap(nodes: NodeModel[]): Map<string, string> {
    const map = new Map<string, string>();
    for (const n of nodes) {
        map.set(n.node_name, n.id);
    }
    return map;
}

/** Get the output port role for a node type. */
function getOutputPortRole(nodeType: NodeType): string {
    switch (nodeType) {
        case NodeType.START: return 'start-start';
        case NodeType.PROJECT: return 'project-out';
        case NodeType.PYTHON: return 'python-out';
        case NodeType.LLM: return 'llm-out-right';
        case NodeType.EDGE: return 'edge-out';
        case NodeType.TABLE: return 'table-out';
        case NodeType.FILE_EXTRACTOR: return 'file-extractor-out';
        case NodeType.AUDIO_TO_TEXT: return 'audio-to-text-out';
        case NodeType.SUBGRAPH: return 'subgraph-out';
        case NodeType.WEBHOOK_TRIGGER: return 'webhook-trigger-out';
        case NodeType.TELEGRAM_TRIGGER: return 'telegram-trigger-out';
        case NodeType.END: return 'end-out';
        default: return 'output';
    }
}

/** Get the input port role for a node type. */
function getInputPortRole(nodeType: NodeType): string {
    switch (nodeType) {
        case NodeType.PROJECT: return 'project-in';
        case NodeType.PYTHON: return 'python-in';
        case NodeType.LLM: return 'llm-out-left';
        case NodeType.EDGE: return 'edge-in';
        case NodeType.TABLE: return 'table-in';
        case NodeType.FILE_EXTRACTOR: return 'file-extractor-in';
        case NodeType.AUDIO_TO_TEXT: return 'audio-to-text-in';
        case NodeType.SUBGRAPH: return 'subgraph-in';
        case NodeType.WEBHOOK_TRIGGER: return 'webhook-trigger-in';
        case NodeType.TELEGRAM_TRIGGER: return 'telegram-trigger-in';
        case NodeType.END: return 'end-in';
        default: return 'input';
    }
}

/**
 * Build connections from simple edges (edge_list).
 * Each edge has start_key and end_key (node names).
 */
function buildEdgeConnections(
    edges: Edge[],
    nameToId: Map<string, string>,
    nodeByName: Map<string, NodeModel>
): ConnectionModel[] {
    const connections: ConnectionModel[] = [];
    for (const edge of edges) {
        const sourceId = nameToId.get(edge.start_key);
        const targetId = nameToId.get(edge.end_key);
        if (!sourceId || !targetId) {
            continue;
        }
        const sourceNode = nodeByName.get(edge.start_key);
        const targetNode = nodeByName.get(edge.end_key);
        if (!sourceNode || !targetNode) continue;

        const sourcePortRole = getOutputPortRole(sourceNode.type);
        const targetPortRole = getInputPortRole(targetNode.type);

        connections.push(makeConnection(
            sourceId,
            targetId,
            `${sourceId}_${sourcePortRole}` as CustomPortId,
            `${targetId}_${targetPortRole}` as CustomPortId,
        ));
    }
    return connections;
}

/**
 * Build connections for conditional edges.
 * A conditional edge has `source` (node name) and `then` (target node name).
 * We already created an EdgeNodeModel for each conditional edge.
 * Now we connect: source → edgeNode → target.
 */
function buildConditionalEdgeConnections(
    conditionalEdges: ConditionalEdge[],
    edgeNodes: EdgeNodeModel[],
    nameToId: Map<string, string>,
    nodeByName: Map<string, NodeModel>
): ConnectionModel[] {
    const connections: ConnectionModel[] = [];

    for (let i = 0; i < conditionalEdges.length; i++) {
        const ce = conditionalEdges[i];
        const edgeNode = edgeNodes[i];

        // source → edgeNode
        const sourceId = nameToId.get(ce.source);
        if (sourceId) {
            const sourceNode = nodeByName.get(ce.source);
            if (sourceNode) {
                const sourcePortRole = getOutputPortRole(sourceNode.type);
                connections.push(makeConnection(
                    sourceId,
                    edgeNode.id,
                    `${sourceId}_${sourcePortRole}` as CustomPortId,
                    `${edgeNode.id}_edge-in` as CustomPortId,
                ));
            }
        }

        // edgeNode → target (then)
        if (ce.then) {
            const targetId = nameToId.get(ce.then);
            if (targetId) {
                const targetNode = nodeByName.get(ce.then);
                if (targetNode) {
                    const targetPortRole = getInputPortRole(targetNode.type);
                    connections.push(makeConnection(
                        edgeNode.id,
                        targetId,
                        `${edgeNode.id}_edge-out` as CustomPortId,
                        `${targetId}_${targetPortRole}` as CustomPortId,
                    ));
                }
            }
        }
    }
    return connections;
}

/**
 * Build connections for decision table nodes.
 * Each condition_group.next_node, default_next_node, next_error_node are
 * node_name references that need to be turned into connections.
 */
function buildDecisionTableConnections(
    decisionTableNodes: DecisionTableNodeModel[],
    nameToId: Map<string, string>,
    nodeByName: Map<string, NodeModel>,
    backendDecisionTables: GetDecisionTableNodeRequest[]
): ConnectionModel[] {
    const connections: ConnectionModel[] = [];

    for (let i = 0; i < decisionTableNodes.length; i++) {
        const dtNode = decisionTableNodes[i];
        const backendDt = backendDecisionTables[i];
        if (!backendDt) continue;

        // Condition group connections
        for (const group of backendDt.condition_groups) {
            if (group.next_node) {
                const targetId = nameToId.get(group.next_node);
                if (targetId) {
                    const targetNode = nodeByName.get(group.next_node);
                    if (targetNode) {
                        const normalizedGroupName = group.group_name.toLowerCase().replace(/\s+/g, '-');
                        connections.push(makeConnection(
                            dtNode.id,
                            targetId,
                            `${dtNode.id}_decision-out-${normalizedGroupName}` as CustomPortId,
                            `${targetId}_${getInputPortRole(targetNode.type)}` as CustomPortId,
                        ));
                    }
                }
            }
        }

        // Default next node
        if (backendDt.default_next_node) {
            const targetId = nameToId.get(backendDt.default_next_node);
            if (targetId) {
                const targetNode = nodeByName.get(backendDt.default_next_node);
                if (targetNode) {
                    connections.push(makeConnection(
                        dtNode.id,
                        targetId,
                        `${dtNode.id}_decision-default` as CustomPortId,
                        `${targetId}_${getInputPortRole(targetNode.type)}` as CustomPortId,
                    ));
                }
            }
        }

        // Error next node
        if (backendDt.next_error_node) {
            const targetId = nameToId.get(backendDt.next_error_node);
            if (targetId) {
                const targetNode = nodeByName.get(backendDt.next_error_node);
                if (targetNode) {
                    connections.push(makeConnection(
                        dtNode.id,
                        targetId,
                        `${dtNode.id}_decision-error` as CustomPortId,
                        `${targetId}_${getInputPortRole(targetNode.type)}` as CustomPortId,
                    ));
                }
            }
        }
    }
    return connections;
}

// ─────────────────────────────────────────────────────────────────────────────
// Public API
// ─────────────────────────────────────────────────────────────────────────────

/**
 * Build a complete FlowModel from a GraphDto by reconstructing nodes from
 * the backend node lists instead of relying on `graph.metadata`.
 *
 * All node types (including notes) are now loaded from dedicated backend tables.
 */
export function buildFlowModelFromGraph(graph: GraphDto): FlowModel {
    let idx = 0;

    // ── 1. Build all nodes from backend lists ────────────────────────────
    const startNodes = (graph.start_node_list ?? []).map(sn => buildStartNode(sn, idx++));
    const crewNodes = (graph.crew_node_list ?? []).map(cn => buildCrewNode(cn, idx++));
    const pythonNodes = (graph.python_node_list ?? []).map(pn => buildPythonNode(pn, idx++));
    const llmNodes = (graph.llm_node_list ?? []).map(ln => buildLLMNode(ln, idx++));
    const fileExtractorNodes = (graph.file_extractor_node_list ?? []).map(n => buildFileExtractorNode(n, idx++));
    const audioToTextNodes = (graph.audio_transcription_node_list ?? []).map(n => buildAudioToTextNode(n, idx++));
    const subGraphNodes = (graph.subgraph_node_list ?? []).map(sn => buildSubGraphNode(sn, idx++));
    const noteNodes = (graph.note_node_list ?? []).map(nn => buildNoteNode(nn, idx++));
    const webhookTriggerNodes = (graph.webhook_trigger_node_list ?? []).map(wn => buildWebhookTriggerNode(wn, idx++));
    const telegramTriggerNodes = (graph.telegram_trigger_node_list ?? []).map(tn => buildTelegramTriggerNode(tn, idx++));
    const endNodes = (graph.end_node_list ?? []).map(en => buildEndNode(en, idx++));
    const decisionTableNodes = (graph.decision_table_node_list ?? []).map(dn => buildDecisionTableNode(dn, idx++));
    const conditionalEdgeNodes = (graph.conditional_edge_list ?? []).map(ce => buildConditionalEdgeNode(ce, idx++));

    // ── 2. Combine all nodes ─────────────────────────────────────────────
    const allNodes: NodeModel[] = [
        ...startNodes,
        ...crewNodes,
        ...pythonNodes,
        ...llmNodes,
        ...fileExtractorNodes,
        ...audioToTextNodes,
        ...subGraphNodes,
        ...noteNodes,
        ...webhookTriggerNodes,
        ...telegramTriggerNodes,
        ...endNodes,
        ...decisionTableNodes,
        ...conditionalEdgeNodes,
    ];

    // ── 3. Build name→ID and name→node maps ─────────────────────────────
    const nameToId = buildNameToIdMap(allNodes);
    const nodeByName = new Map<string, NodeModel>();
    for (const n of allNodes) {
        nodeByName.set(n.node_name, n);
    }

    // ── 4. Build connections from backend edge data ──────────────────────
    const edgeConnections = buildEdgeConnections(
        graph.edge_list ?? [],
        nameToId,
        nodeByName
    );

    const conditionalEdgeConnections = buildConditionalEdgeConnections(
        graph.conditional_edge_list ?? [],
        conditionalEdgeNodes,
        nameToId,
        nodeByName
    );

    const decisionTableConnections = buildDecisionTableConnections(
        decisionTableNodes,
        nameToId,
        nodeByName,
        graph.decision_table_node_list ?? []
    );

    // ── 5. Combine all connections ───────────────────────────────────────
    const allConnections: ConnectionModel[] = [
        ...edgeConnections,
        ...conditionalEdgeConnections,
        ...decisionTableConnections,
    ];

    return {
        nodes: allNodes,
        connections: allConnections,
    };
}
