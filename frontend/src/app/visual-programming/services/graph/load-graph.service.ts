/**
 * Pure functions to build a FlowModel from a GraphDto.
 *
 * Reconstructs the node list and connections from the individual backend
 * node/edge lists.  UI-only metadata (position, color, icon, size) is read
 * from each node's `metadata` JSON field.
 *
 * Edges and conditional edges now use backend node IDs (integers) instead of
 * node names, so connections are resolved via a backendId → UUID map.
 */

import { v4 as uuidv4 } from 'uuid';

import { GraphDto } from '../../../features/flows/models/graph.model';
import { GetAudioToTextNodeRequest } from '../../../pages/flows-page/components/flow-visual-programming/models/audio-to-text.model';
import { GetCodeAgentNodeRequest } from '../../../pages/flows-page/components/flow-visual-programming/models/code-agent-node.model';
import { ConditionalEdge } from '../../../pages/flows-page/components/flow-visual-programming/models/conditional-edge.model';
import { CrewNode } from '../../../pages/flows-page/components/flow-visual-programming/models/crew-node.model';
import { GetDecisionTableNodeRequest } from '../../../pages/flows-page/components/flow-visual-programming/models/decision-table-node.model';
import { Edge } from '../../../pages/flows-page/components/flow-visual-programming/models/edge.model';
import { EndNode } from '../../../pages/flows-page/components/flow-visual-programming/models/end-node.model';
import { GetFileExtractorNodeRequest } from '../../../pages/flows-page/components/flow-visual-programming/models/file-extractor.model';
import { GraphNote } from '../../../pages/flows-page/components/flow-visual-programming/models/graph-note.model';
import { GetLLMNodeRequest } from '../../../pages/flows-page/components/flow-visual-programming/models/llm-node.model';
import { PythonNode } from '../../../pages/flows-page/components/flow-visual-programming/models/python-node.model';
import { StartNode } from '../../../pages/flows-page/components/flow-visual-programming/models/start-node.model';
import { SubGraphNode } from '../../../pages/flows-page/components/flow-visual-programming/models/subgraph-node.model';
import { GetTelegramTriggerNodeRequest } from '../../../pages/flows-page/components/flow-visual-programming/models/telegram-trigger.model';
import { GetWebhookTriggerNodeRequest } from '../../../pages/flows-page/components/flow-visual-programming/models/webhook-trigger';
import { NODE_COLORS, NODE_ICONS } from '../../core/enums/node-config';
import { NodeType } from '../../core/enums/node-type';
import { ConnectionModel } from '../../core/models/connection.model';
import { FlowModel } from '../../core/models/flow.model';
import {
    AudioToTextNodeModel,
    CodeAgentNodeModel,
    DecisionTableNodeModel,
    EdgeNodeModel,
    EndNodeModel,
    FileExtractorNodeModel,
    GraphNoteModel,
    LLMNodeModel,
    NodeModel,
    ProjectNodeModel,
    PythonNodeModel,
    StartNodeModel,
    SubGraphNodeModel,
    TelegramTriggerNodeModel,
    WebhookTriggerNodeModel,
} from '../../core/models/node.model';
import { CustomPortId } from '../../core/models/port.model';
import { NodeUIMetadata } from './save-graph.types';

// ─────────────────────────────────────────────────────────────────────────────
// Helpers
// ─────────────────────────────────────────────────────────────────────────────

function readUIMetadata(
    metadata: Record<string, unknown> | undefined | null,
    nodeType: NodeType,
    fallbackIndex: number
): NodeUIMetadata {
    const m = metadata ?? {};
    const position = m['position'] as { x?: number; y?: number } | undefined;
    const size = m['size'] as { width?: number; height?: number } | undefined;

    return {
        position: {
            x: position?.x ?? 100 + (fallbackIndex % 5) * 400,
            y: position?.y ?? 100 + Math.floor(fallbackIndex / 5) * 200,
        },
        color: typeof m['color'] === 'string' ? m['color'] : (NODE_COLORS[nodeType] ?? '#685fff'),
        icon: typeof m['icon'] === 'string' ? m['icon'] : (NODE_ICONS[nodeType] ?? 'ti ti-code'),
        size: {
            width: size?.width ?? getDefaultSize(nodeType).width,
            height: size?.height ?? getDefaultSize(nodeType).height,
        },
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
        case NodeType.EDGE:
            return { width: 300, height: 180 };
        default:
            return { width: 330, height: 60 };
    }
}

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
// Node builders
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

        color: ui.color,
        icon: ui.icon,
        input_map: cn.input_map ?? {},
        output_variable_path: cn.output_variable_path,
        stream_config: cn.stream_config ?? {},
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

        color: ui.color,
        icon: ui.icon,
        input_map: pn.input_map ?? {},
        output_variable_path: pn.output_variable_path,
        stream_config: pn.stream_config ?? {},
        size: ui.size,
    };
}

function buildCodeAgentNode(ca: GetCodeAgentNodeRequest, idx: number): CodeAgentNodeModel {
    const ui = readUIMetadata(ca.metadata, NodeType.CODE_AGENT, idx);
    return {
        id: uuidv4(),
        backendId: ca.id,
        category: 'web',
        type: NodeType.CODE_AGENT,
        node_name: ca.node_name,
        data: {
            llm_config_id: ca.llm_config,
            agent_mode: ca.agent_mode ?? 'build',
            session_id: ca.session_id ?? '',
            system_prompt: ca.system_prompt ?? '',
            stream_handler_code: ca.stream_handler_code ?? '',
            libraries: ca.libraries ?? [],
            polling_interval_ms: ca.polling_interval_ms ?? 1000,
            silence_indicator_s: ca.silence_indicator_s ?? 3,
            indicator_repeat_s: ca.indicator_repeat_s ?? 5,
            chunk_timeout_s: ca.chunk_timeout_s ?? 30,
            inactivity_timeout_s: ca.inactivity_timeout_s ?? 120,
            max_wait_s: ca.max_wait_s ?? 300,
            output_schema: ca.output_schema ?? {},
        },
        position: ui.position,
        ports: null,

        color: ui.color,
        icon: ui.icon,
        input_map: ca.input_map ?? {},
        output_variable_path: ca.output_variable_path,
        stream_config: ca.stream_config ?? {},
        size: ui.size,
    };
}

function buildLLMNode(ln: GetLLMNodeRequest, idx: number): LLMNodeModel {
    const ui = readUIMetadata(ln.metadata, NodeType.LLM, idx);
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

        color: ui.color,
        icon: ui.icon,
        input_map: n.input_map ?? {},
        output_variable_path: n.output_variable_path,
        size: ui.size,
    };
}

function buildSubGraphNode(sn: SubGraphNode, idx: number): SubGraphNodeModel {
    const ui = readUIMetadata(sn.metadata, NodeType.SUBGRAPH, idx);
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

        color: ui.color,
        icon: ui.icon,
        input_map: {} as Record<string, unknown>,
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

        color: ui.color,
        icon: ui.icon,
        input_map: {},
        output_variable_path: null,
        size: ui.size,
    };
}

function buildGraphNote(nn: GraphNote, idx: number): GraphNoteModel {
    const ui = readUIMetadata(nn.metadata, NodeType.NOTE, idx);
    return {
        id: uuidv4(),
        backendId: nn.id,
        category: 'web',
        type: NodeType.NOTE,
        node_name: nn.node_name ?? `Note (#${idx + 1})`,
        data: {
            content: nn.content,
            backgroundColor: nn.metadata?.['backgroundColor'] as string | undefined,
        },
        position: ui.position,
        ports: null,

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
                // These will be post-processed to resolve backend IDs → UUIDs
                default_next_node: null,
                next_error_node: null,
                condition_groups: dn.condition_groups.map((g) => ({
                    group_name: g.group_name,
                    group_type: g.group_type as 'simple' | 'complex',
                    expression: g.expression,
                    conditions: g.conditions.map((c) => ({
                        condition_name: c.condition_name,
                        condition: c.condition,
                    })),
                    manipulation: g.manipulation,
                    next_node: null,
                    valid: true,
                    order: g.order,
                })),
            },
        },
        position: ui.position,
        ports: null,

        color: ui.color,
        icon: ui.icon,
        input_map: {} as Record<string, unknown>,
        output_variable_path: null,
        size: ui.size,
    };
}

function buildConditionalEdgeNode(ce: ConditionalEdge, idx: number): EdgeNodeModel {
    const ui = readUIMetadata(ce.metadata, NodeType.EDGE, idx);
    const nodeName = 'Conditional Edge';
    return {
        id: uuidv4(),
        backendId: ce.id,
        category: 'web',
        type: NodeType.EDGE,
        node_name: nodeName,
        data: {
            source: null,
            then: null,
            python_code: {
                name: nodeName,
                libraries: ce.python_code.libraries,
                code: ce.python_code.code,
                entrypoint: ce.python_code.entrypoint,
            },
            input_map: ce.input_map ?? {},
        },
        position: ui.position,
        ports: null,

        color: ui.color,
        icon: ui.icon,
        input_map: ce.input_map ?? {},
        output_variable_path: null,
        size: ui.size,
    };
}

// ─────────────────────────────────────────────────────────────────────────────
// Connection builders — now use backendId → UUID maps
// ─────────────────────────────────────────────────────────────────────────────

function getOutputPortRole(nodeType: NodeType): string {
    switch (nodeType) {
        case NodeType.START:
            return 'start-start';
        case NodeType.PROJECT:
            return 'project-out';
        case NodeType.PYTHON:
            return 'python-out';
        case NodeType.LLM:
            return 'llm-out-right';
        case NodeType.EDGE:
            return 'edge-out';
        case NodeType.TABLE:
            return 'decision-default';
        case NodeType.FILE_EXTRACTOR:
            return 'file-extractor-out';
        case NodeType.AUDIO_TO_TEXT:
            return 'audio-to-text-out';
        case NodeType.SUBGRAPH:
            return 'subgraph-out';
        case NodeType.WEBHOOK_TRIGGER:
            return 'webhook-trigger-out';
        case NodeType.TELEGRAM_TRIGGER:
            return 'telegram-trigger-out';
        case NodeType.END:
            return 'end-out';
        case NodeType.CODE_AGENT:
            return 'code-agent-out';
        default:
            return 'output';
    }
}

function getInputPortRole(nodeType: NodeType): string {
    switch (nodeType) {
        case NodeType.PROJECT:
            return 'project-in';
        case NodeType.PYTHON:
            return 'python-in';
        case NodeType.LLM:
            return 'llm-out-left';
        case NodeType.EDGE:
            return 'edge-in';
        case NodeType.TABLE:
            return 'table-in';
        case NodeType.FILE_EXTRACTOR:
            return 'file-extractor-in';
        case NodeType.AUDIO_TO_TEXT:
            return 'audio-to-text-in';
        case NodeType.SUBGRAPH:
            return 'subgraph-in';
        case NodeType.WEBHOOK_TRIGGER:
            return 'webhook-trigger-in';
        case NodeType.TELEGRAM_TRIGGER:
            return 'telegram-trigger-in';
        case NodeType.END:
            return 'end-in';
        case NodeType.CODE_AGENT:
            return 'code-agent-in';
        default:
            return 'input';
    }
}

/**
 * Build connections from simple edges.
 * Each edge has start_node_id / end_node_id (backend integer IDs).
 */
function buildEdgeConnections(
    edges: Edge[],
    backendIdToUuid: Map<number, string>,
    nodeByBackendId: Map<number, NodeModel>
): ConnectionModel[] {
    const connections: ConnectionModel[] = [];
    for (const edge of edges) {
        const sourceUuid = backendIdToUuid.get(edge.start_node_id);
        const targetUuid = backendIdToUuid.get(edge.end_node_id);
        if (!sourceUuid || !targetUuid) continue;

        const sourceNode = nodeByBackendId.get(edge.start_node_id);
        const targetNode = nodeByBackendId.get(edge.end_node_id);
        if (!sourceNode || !targetNode) continue;

        // DT connections are handled by buildDecisionTableConnections;
        // EDGE connections are handled by buildConditionalEdgeConnections.
        if (sourceNode.type === NodeType.TABLE || sourceNode.type === NodeType.EDGE) continue;
        if (targetNode.type === NodeType.EDGE) continue;

        const sourcePortRole = getOutputPortRole(sourceNode.type);
        const targetPortRole = getInputPortRole(targetNode.type);

        connections.push(
            makeConnection(
                sourceUuid,
                targetUuid,
                `${sourceUuid}_${sourcePortRole}` as CustomPortId,
                `${targetUuid}_${targetPortRole}` as CustomPortId
            )
        );
    }
    return connections;
}

/**
 * Build connections for conditional edges.
 * source_node_id identifies which node feeds into the edge node.
 * then_node_id (from metadata) identifies the target node.
 */
function buildConditionalEdgeConnections(
    conditionalEdges: ConditionalEdge[],
    edgeNodes: EdgeNodeModel[],
    backendIdToUuid: Map<number, string>,
    nodeByBackendId: Map<number, NodeModel>,
    decisionTableNodes: DecisionTableNodeModel[]
): ConnectionModel[] {
    void decisionTableNodes;
    const connections: ConnectionModel[] = [];

    for (let i = 0; i < conditionalEdges.length; i++) {
        const ce = conditionalEdges[i];
        const edgeNode = edgeNodes[i];

        // source → edgeNode (using source_node_id)
        const sourceUuid = backendIdToUuid.get(ce.source_node_id);
        if (sourceUuid) {
            const sourceNode = nodeByBackendId.get(ce.source_node_id);
            if (sourceNode) {
                let sourcePortId: CustomPortId;
                if (sourceNode.type === NodeType.TABLE) {
                    const dtPort = resolveDTPortForTarget(sourceNode as DecisionTableNodeModel, edgeNode.id);
                    sourcePortId = `${sourceUuid}_${dtPort}` as CustomPortId;
                } else {
                    sourcePortId = `${sourceUuid}_${getOutputPortRole(sourceNode.type)}` as CustomPortId;
                }
                connections.push(
                    makeConnection(sourceUuid, edgeNode.id, sourcePortId, `${edgeNode.id}_edge-in` as CustomPortId)
                );
            }
        } else if (ce.source_node_id != null) {
            console.warn(
                `[CE-connections] CE backendId=${ce.id}: source_node_id=${ce.source_node_id} not found in backendIdToUuid`
            );
        }

        // edgeNode → target (using then_node_id from metadata)
        const thenNodeId = (ce.metadata as { then_node_id?: number | null } | undefined)?.then_node_id ?? null;
        if (thenNodeId != null) {
            const targetUuid = backendIdToUuid.get(thenNodeId);
            if (targetUuid) {
                const targetNode = nodeByBackendId.get(thenNodeId);
                if (targetNode) {
                    const targetPortRole = getInputPortRole(targetNode.type);
                    connections.push(
                        makeConnection(
                            edgeNode.id,
                            targetUuid,
                            `${edgeNode.id}_edge-out` as CustomPortId,
                            `${targetUuid}_${targetPortRole}` as CustomPortId
                        )
                    );
                }
            } else {
                console.warn(
                    `[CE-connections] CE backendId=${ce.id}: then_node_id=${thenNodeId} not found in backendIdToUuid`
                );
            }
        }
    }
    return connections;
}

/**
 * Determines which DT output port connects to a given target node UUID.
 * Checks default_next_node, next_error_node, and condition group next_node fields.
 */
function resolveDTPortForTarget(dtNode: DecisionTableNodeModel, targetUuid: string): string {
    const table = dtNode.data?.table;
    if (!table) return 'decision-default';

    if (table.default_next_node === targetUuid) return 'decision-default';
    if (table.next_error_node === targetUuid) return 'decision-error';

    for (const group of table.condition_groups ?? []) {
        if (group.next_node === targetUuid) {
            const normalized = group.group_name.toLowerCase().replace(/\s+/g, '-');
            return `decision-out-${normalized}`;
        }
    }

    return 'decision-default';
}

/**
 * Build connections for decision table nodes.
 * condition_group.next_node_id, default_next_node_id, next_error_node_id
 * are all backend integer IDs.
 */
function buildDecisionTableConnections(
    decisionTableNodes: DecisionTableNodeModel[],
    backendIdToUuid: Map<number, string>,
    nodeByBackendId: Map<number, NodeModel>,
    backendDecisionTables: GetDecisionTableNodeRequest[]
): ConnectionModel[] {
    const connections: ConnectionModel[] = [];

    for (let i = 0; i < decisionTableNodes.length; i++) {
        const dtNode = decisionTableNodes[i];
        const backendDt = backendDecisionTables[i];
        if (!backendDt) {
            console.warn(`[DT-connections] No backend DT found at index ${i} for dtNode ${dtNode.id}`);
            continue;
        }

        for (const group of backendDt.condition_groups) {
            if (group.next_node_id != null) {
                const targetUuid = backendIdToUuid.get(group.next_node_id);
                if (targetUuid) {
                    const targetNode = nodeByBackendId.get(group.next_node_id);
                    if (targetNode) {
                        if (targetNode.type === NodeType.EDGE) {
                        } else {
                            const normalizedGroupName = group.group_name.toLowerCase().replace(/\s+/g, '-');
                            connections.push(
                                makeConnection(
                                    dtNode.id,
                                    targetUuid,
                                    `${dtNode.id}_decision-out-${normalizedGroupName}` as CustomPortId,
                                    `${targetUuid}_${getInputPortRole(targetNode.type)}` as CustomPortId
                                )
                            );
                        }
                    }
                } else {
                    console.warn(
                        `[DT-connections] Group "${group.group_name}": next_node_id=${group.next_node_id} not found in backendIdToUuid`
                    );
                }
            }
        }

        if (backendDt.default_next_node_id != null) {
            const targetUuid = backendIdToUuid.get(backendDt.default_next_node_id);
            if (targetUuid) {
                const targetNode = nodeByBackendId.get(backendDt.default_next_node_id);
                if (targetNode) {
                    // Skip EDGE targets — those connections are handled by buildConditionalEdgeConnections
                    if (targetNode.type === NodeType.EDGE) {
                    } else {
                        connections.push(
                            makeConnection(
                                dtNode.id,
                                targetUuid,
                                `${dtNode.id}_decision-default` as CustomPortId,
                                `${targetUuid}_${getInputPortRole(targetNode.type)}` as CustomPortId
                            )
                        );
                    }
                }
            } else {
                console.warn(
                    `[DT-connections] default_next_node_id=${backendDt.default_next_node_id} not found in backendIdToUuid (map size=${backendIdToUuid.size})`
                );
            }
        }

        if (backendDt.next_error_node_id != null) {
            const targetUuid = backendIdToUuid.get(backendDt.next_error_node_id);
            if (targetUuid) {
                const targetNode = nodeByBackendId.get(backendDt.next_error_node_id);
                if (targetNode) {
                    if (targetNode.type === NodeType.EDGE) {
                    } else {
                        connections.push(
                            makeConnection(
                                dtNode.id,
                                targetUuid,
                                `${dtNode.id}_decision-error` as CustomPortId,
                                `${targetUuid}_${getInputPortRole(targetNode.type)}` as CustomPortId
                            )
                        );
                    }
                }
            } else {
                console.warn(
                    `[DT-connections] next_error_node_id=${backendDt.next_error_node_id} not found in backendIdToUuid`
                );
            }
        }
    }

    return connections;
}

// ─────────────────────────────────────────────────────────────────────────────
// Post-processing: resolve decision table backend ID refs → UUIDs
// ─────────────────────────────────────────────────────────────────────────────

function resolveDecisionTableNodeRefs(
    decisionTableNodes: DecisionTableNodeModel[],
    backendDecisionTables: GetDecisionTableNodeRequest[],
    backendIdToUuid: Map<number, string>
): void {
    for (let i = 0; i < decisionTableNodes.length; i++) {
        const dtNode = decisionTableNodes[i];
        const backendDt = backendDecisionTables.find((d) => d.id === dtNode.backendId);
        if (!backendDt) continue;

        const table = dtNode.data.table;

        table.default_next_node =
            backendDt.default_next_node_id != null
                ? (backendIdToUuid.get(backendDt.default_next_node_id) ?? null)
                : null;
        table.next_error_node =
            backendDt.next_error_node_id != null ? (backendIdToUuid.get(backendDt.next_error_node_id) ?? null) : null;

        for (let j = 0; j < table.condition_groups.length; j++) {
            const group = table.condition_groups[j];
            const backendGroup = backendDt.condition_groups[j];
            if (backendGroup) {
                group.next_node =
                    backendGroup.next_node_id != null ? (backendIdToUuid.get(backendGroup.next_node_id) ?? null) : null;
            }
        }
    }
}

/**
 * Post-process conditional edge nodes: fill in data.source and data.then
 * using the backendIdToUuid map so the UI can display connections properly.
 */
function resolveConditionalEdgeNodeRefs(
    conditionalEdges: ConditionalEdge[],
    edgeNodes: EdgeNodeModel[],
    backendIdToUuid: Map<number, string>,
    nodeByBackendId: Map<number, NodeModel>
): void {
    for (let i = 0; i < conditionalEdges.length; i++) {
        const ce = conditionalEdges[i];
        const edgeNode = edgeNodes[i];

        const sourceNode = nodeByBackendId.get(ce.source_node_id);
        edgeNode.data.source = sourceNode?.node_name ?? null;

        const thenNodeId = (ce.metadata as { then_node_id?: number | null } | undefined)?.then_node_id ?? null;
        if (thenNodeId != null) {
            const targetNode = nodeByBackendId.get(thenNodeId);
            edgeNode.data.then = targetNode?.node_name ?? null;
        }
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// Public API
// ─────────────────────────────────────────────────────────────────────────────

export function buildFlowModelFromGraph(graph: GraphDto): FlowModel {
    let idx = 0;

    // ── 1. Build all nodes from backend lists ────────────────────────────
    const startNodes = (graph.start_node_list ?? []).map((sn) => buildStartNode(sn, idx++));
    const crewNodes = (graph.crew_node_list ?? []).map((cn) => buildCrewNode(cn, idx++));
    const pythonNodes = (graph.python_node_list ?? []).map((pn) => buildPythonNode(pn, idx++));
    const llmNodes = (graph.llm_node_list ?? []).map((ln) => buildLLMNode(ln, idx++));
    const fileExtractorNodes = (graph.file_extractor_node_list ?? []).map((n) => buildFileExtractorNode(n, idx++));
    const audioToTextNodes = (graph.audio_transcription_node_list ?? []).map((n) => buildAudioToTextNode(n, idx++));
    const subGraphNodes = (graph.subgraph_node_list ?? []).map((sn) => buildSubGraphNode(sn, idx++));
    const noteNodes = (graph.graph_note_list ?? []).map((nn) => buildGraphNote(nn, idx++));
    const webhookTriggerNodes = (graph.webhook_trigger_node_list ?? []).map((wn) => buildWebhookTriggerNode(wn, idx++));
    const telegramTriggerNodes = (graph.telegram_trigger_node_list ?? []).map((tn) =>
        buildTelegramTriggerNode(tn, idx++)
    );
    const endNodes = (graph.end_node_list ?? []).map((en) => buildEndNode(en, idx++));
    const codeAgentNodes = (graph.code_agent_node_list ?? []).map((ca) => buildCodeAgentNode(ca, idx++));
    const decisionTableNodes = (graph.decision_table_node_list ?? []).map((dn) => buildDecisionTableNode(dn, idx++));
    const conditionalEdgeNodes = (graph.conditional_edge_list ?? []).map((ce) => buildConditionalEdgeNode(ce, idx++));

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
        ...codeAgentNodes,
        ...decisionTableNodes,
        ...conditionalEdgeNodes,
    ];

    // ── 3. Build backendId → UUID and backendId → node maps ──────────────
    const backendIdToUuid = new Map<number, string>();
    const nodeByBackendId = new Map<number, NodeModel>();
    for (const n of allNodes) {
        if (n.backendId != null) {
            if (backendIdToUuid.has(n.backendId)) {
                const existing = nodeByBackendId.get(n.backendId);
                console.warn(
                    `[load-graph] backendId collision: id=${n.backendId} claimed by "${n.node_name}" (type=${n.type}) ` +
                        `but already used by "${existing?.node_name}" (type=${existing?.type}). ` +
                        `ConditionalEdge IDs are in a separate namespace from global node IDs — this may cause connection issues.`
                );
            }
            backendIdToUuid.set(n.backendId, n.id);
            nodeByBackendId.set(n.backendId, n);
        }
    }
    // ── 4. Post-process: resolve backend ID refs → UUIDs in decision tables
    resolveDecisionTableNodeRefs(decisionTableNodes, graph.decision_table_node_list ?? [], backendIdToUuid);

    // ── 5. Post-process: resolve conditional edge source/then names ──────
    resolveConditionalEdgeNodeRefs(
        graph.conditional_edge_list ?? [],
        conditionalEdgeNodes,
        backendIdToUuid,
        nodeByBackendId
    );

    // ── 6. Build connections from backend edge data ──────────────────────
    const edgeConnections = buildEdgeConnections(graph.edge_list ?? [], backendIdToUuid, nodeByBackendId);

    const conditionalEdgeConnections = buildConditionalEdgeConnections(
        graph.conditional_edge_list ?? [],
        conditionalEdgeNodes,
        backendIdToUuid,
        nodeByBackendId,
        decisionTableNodes
    );

    const decisionTableConnections = buildDecisionTableConnections(
        decisionTableNodes,
        backendIdToUuid,
        nodeByBackendId,
        graph.decision_table_node_list ?? []
    );

    // ── 7. Combine all connections ───────────────────────────────────────
    const allConnections: ConnectionModel[] = [
        ...edgeConnections,
        ...conditionalEdgeConnections,
        ...decisionTableConnections,
    ];

    const badConns = allConnections.filter((c) => c.sourcePortId.includes('table-out'));
    if (badConns.length) {
        console.error('[load-graph] BUG: connections with table-out port still exist!', badConns);
    }
    return {
        nodes: allNodes,
        connections: allConnections,
    };
}
