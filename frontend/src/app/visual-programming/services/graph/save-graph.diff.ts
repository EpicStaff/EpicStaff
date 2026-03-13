/**
 * Pure functions — no Angular/RxJS dependencies.
 *
 * Responsibilities:
 *   1. extractPreviousState  — pull the current backend state out of GraphDto
 *   2. extractNewState       — pull the current UI state out of FlowModel
 *   3. getGraphDiff           — compare the two states, return what changed
 *   4. Payload builders      — convert UI nodes into API request bodies
 */

import { isEqual } from 'lodash';

import { GraphDto } from '../../../features/flows/models/graph.model';
import { FlowModel } from '../../core/models/flow.model';
import { NodeType } from '../../core/enums/node-type';
import { ConnectionModel } from '../../core/models/connection.model';
import {
    BaseNodeModel,
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
    NodeModel,
} from '../../core/models/node.model';
import { GetProjectRequest } from '../../../features/projects/models/project.model';
import { CreateCrewNodeRequest } from '../../../pages/flows-page/components/flow-visual-programming/models/crew-node.model';
import { CreatePythonNodeRequest } from '../../../pages/flows-page/components/flow-visual-programming/models/python-node.model';
import { CreateLLMNodeRequest } from '../../../pages/flows-page/components/flow-visual-programming/models/llm-node.model';
import { CreateFileExtractorNodeRequest } from '../../../pages/flows-page/components/flow-visual-programming/models/file-extractor.model';
import { CreateAudioToTextNodeRequest } from '../../../pages/flows-page/components/flow-visual-programming/models/audio-to-text.model';
import { CreateSubGraphNodeRequest } from '../../../pages/flows-page/components/flow-visual-programming/models/subgraph-node.model';
import { CreateWebhookTriggerNodeRequest } from '../../../pages/flows-page/components/flow-visual-programming/models/webhook-trigger';
import { CreateTelegramTriggerNodeRequest } from '../../../pages/flows-page/components/flow-visual-programming/models/telegram-trigger.model';
import { CreateConditionalEdgeRequest } from '../../../pages/flows-page/components/flow-visual-programming/models/conditional-edge.model';
import { CreateEdgeRequest } from '../../../pages/flows-page/components/flow-visual-programming/models/edge.model';
import { CreateEndNodeRequest } from '../../../pages/flows-page/components/flow-visual-programming/models/end-node.model';
import {
    CreateConditionGroupRequest,
    CreateDecisionTableNodeRequest,
} from '../../../pages/flows-page/components/flow-visual-programming/models/decision-table-node.model';
import { NoteNode, CreateNoteNodeRequest } from '../../../pages/flows-page/components/flow-visual-programming/models/note-node.model';

import {
    NodeDiff,
    GraphPreviousState,
    GraphNewState,
    GraphDiff,
    ResolvedConditionalEdge,
    NodeUIMetadata,
    getUIMetadataForComparison,
} from './save-graph.types';
import {
    getCrewNodeForComparisonFromBackend,
    getCrewNodeForComparisonFromUI,
    getPythonNodeForComparisonFromBackend,
    getPythonNodeForComparisonFromUI,
    getLLMNodeForComparisonFromBackend,
    getLLMNodeForComparisonFromUI,
    getFileExtractorNodeForComparisonFromBackend,
    getFileExtractorNodeForComparisonFromUI,
    getAudioToTextNodeForComparisonFromBackend,
    getAudioToTextNodeForComparisonFromUI,
    getSubGraphNodeForComparisonFromBackend,
    getSubGraphNodeForComparisonFromUI,
    getWebhookTriggerNodeForComparisonFromBackend,
    getWebhookTriggerNodeForComparisonFromUI,
    getTelegramTriggerNodeForComparisonFromBackend,
    getTelegramTriggerNodeForComparisonFromUI,
    getConditionalEdgeForComparisonFromBackend,
    getConditionalEdgeForComparisonFromUI,
    getDecisionTableNodeForComparisonFromBackend,
    getDecisionTableNodeForComparisonFromUI,
    getEndNodeForComparisonFromBackend,
    getEndNodeForComparisonFromUI,
    getNoteNodeForComparisonFromBackend,
    getNoteNodeForComparisonFromUI,
} from './save-graph.comparators';

// getUIMetadataForComparison is imported from save-graph.types.ts

// ─────────────────────────────────────────────────────────────────────────────
// Generic diff utility
// ─────────────────────────────────────────────────────────────────────────────

/**
 * Diffs two lists by matching UI nodes to backend nodes via `backendId`.
 *
 * - UI node with `backendId != null` that matches a backend `id` → compare for update
 * - UI node with `backendId == null` → create (new node)
 * - Backend node whose `id` wasn't claimed by any UI node → delete
 *
 * Uses deep equality (lodash isEqual) to decide whether a matched pair
 * actually changed and needs an update request.
 */
export function diffByKey<TBackend extends { id: number }, TUI>(
    backendNodes: TBackend[],
    uiNodes: TUI[],
    /** Extract the backend integer ID from a UI node (typically `n.backendId`). Returns null for new nodes. */
    getUIBackendId: (node: TUI) => number | null,
    toComparableFromBackend: (node: TBackend) => unknown,
    toComparableFromUI: (node: TUI) => unknown,
    nodeTypeName: string = 'Node'
): NodeDiff<TBackend, TUI> {
    // Map backend nodes by their integer ID
    const backendMap = new Map<number, TBackend>();
    for (const node of backendNodes) {
        backendMap.set(node.id, node);
    }

    const toDelete: TBackend[] = [];
    const toCreate: TUI[] = [];
    const toUpdate: Array<{ backend: TBackend; ui: TUI }> = [];
    const matchedBackendIds = new Set<number>();

    for (const uiNode of uiNodes) {
        const bid = getUIBackendId(uiNode);

        if (bid == null) {
            // New node — no backend counterpart
            toCreate.push(uiNode);
            continue;
        }

        const backendNode = backendMap.get(bid);
        if (!backendNode) {
            // backendId was set but the backend no longer has it — treat as create
            toCreate.push(uiNode);
            continue;
        }

        matchedBackendIds.add(bid);

        const backendComparable = toComparableFromBackend(backendNode);
        const uiComparable = toComparableFromUI(uiNode);
        const areEqual = isEqual(backendComparable, uiComparable);

        if (!areEqual) {
            toUpdate.push({ backend: backendNode, ui: uiNode });
        }
    }

    // Backend nodes not matched by any UI node → delete
    for (const [id, backendNode] of backendMap) {
        if (!matchedBackendIds.has(id)) {
            toDelete.push(backendNode);
        }
    }

    return { toDelete, toCreate, toUpdate };
}

// ─────────────────────────────────────────────────────────────────────────────
// Step 1 — Extract previous state (backend → structured object)
// ─────────────────────────────────────────────────────────────────────────────

export function extractPreviousState(graph: GraphDto): GraphPreviousState {
    return {
        crewNodes: graph.crew_node_list ?? [],
        pythonNodes: graph.python_node_list ?? [],
        llmNodes: graph.llm_node_list ?? [],
        fileExtractorNodes: graph.file_extractor_node_list ?? [],
        audioToTextNodes: graph.audio_transcription_node_list ?? [],
        subGraphNodes: graph.subgraph_node_list ?? [],
        webhookTriggerNodes: graph.webhook_trigger_node_list ?? [],
        telegramTriggerNodes: graph.telegram_trigger_node_list ?? [],
        conditionalEdges: graph.conditional_edge_list ?? [],
        edges: graph.edge_list ?? [],
        endNodes: graph.end_node_list ?? [],
        decisionTableNodes: graph.decision_table_node_list ?? [],
        noteNodes: graph.note_node_list ?? [],
    };
}

// ─────────────────────────────────────────────────────────────────────────────
// Step 2 — Extract new state (UI FlowModel → structured object)
// ─────────────────────────────────────────────────────────────────────────────

/** Resolves a node ID (UUID) or already-a-name to a node_name using the UI node list. */
function resolveNodeName(idOrName: string | null, allNodes: NodeModel[]): string | null {
    if (!idOrName) return null;
    const match = allNodes.find(n => n.id === idOrName);
    return match ? match.node_name : idOrName;
}

/**
 * Resolves each EdgeNodeModel to its source and target node names.
 * - source: the node that connects INTO this edge node (where the edge node is the target)
 * - target: the node that this edge node connects TO (where the edge node is the source)
 */
function resolveConditionalEdges(
    edgeNodes: EdgeNodeModel[],
    connections: ConnectionModel[],
    allNodes: NodeModel[]
): ResolvedConditionalEdge[] {
    return edgeNodes.map(edgeNode => {
        const incomingConnection = connections.find(c => c.targetNodeId === edgeNode.id);
        const sourceNode = incomingConnection
            ? allNodes.find(n => n.id === incomingConnection.sourceNodeId)
            : null;

        const outgoingConnection = connections.find(c => c.sourceNodeId === edgeNode.id);
        const targetNode = outgoingConnection
            ? allNodes.find(n => n.id === outgoingConnection.targetNodeId)
            : null;

        return {
            edgeNode,
            sourceName: sourceNode?.node_name ?? null,
            targetName: targetNode?.node_name ?? null,
        };
    });
}

/**
 * Converts valid flow connections into flat {start_key, end_key} pairs,
 * filtering out connections that involve EDGE or TABLE nodes.
 */
function resolveEdges(
    connections: ConnectionModel[],
    allNodes: NodeModel[]
): Array<{ start_key: string; end_key: string }> {
    const nodeById = new Map(allNodes.map(n => [n.id, n]));
    const result: Array<{ start_key: string; end_key: string }> = [];

    for (const conn of connections) {
        const source = nodeById.get(conn.sourceNodeId);
        const target = nodeById.get(conn.targetNodeId);
        if (!source || !target) continue;
        if (source.type === NodeType.EDGE || target.type === NodeType.EDGE) continue;
        if (source.type === NodeType.TABLE) continue;
        result.push({ start_key: source.node_name, end_key: target.node_name });
    }

    return result;
}

export function extractNewState(flowState: FlowModel): GraphNewState {
    const { nodes, connections } = flowState;

    const edgeNodeModels = nodes.filter(n => n.type === NodeType.EDGE) as EdgeNodeModel[];

    return {
        crewNodes: nodes.filter(n => n.type === NodeType.PROJECT) as ProjectNodeModel[],
        pythonNodes: nodes.filter(n => n.type === NodeType.PYTHON) as PythonNodeModel[],
        llmNodes: nodes.filter(n => n.type === NodeType.LLM) as LLMNodeModel[],
        fileExtractorNodes: nodes.filter(n => n.type === NodeType.FILE_EXTRACTOR) as FileExtractorNodeModel[],
        audioToTextNodes: nodes.filter(n => n.type === NodeType.AUDIO_TO_TEXT) as AudioToTextNodeModel[],
        subGraphNodes: nodes.filter(n => n.type === NodeType.SUBGRAPH) as SubGraphNodeModel[],
        webhookTriggerNodes: nodes.filter(n => n.type === NodeType.WEBHOOK_TRIGGER) as WebhookTriggerNodeModel[],
        telegramTriggerNodes: nodes.filter(n => n.type === NodeType.TELEGRAM_TRIGGER) as TelegramTriggerNodeModel[],
        conditionalEdges: resolveConditionalEdges(edgeNodeModels, connections, nodes),
        edges: resolveEdges(connections, nodes),
        noteNodes: nodes.filter(n => n.type === NodeType.NOTE) as NoteNodeModel[],
        endNodes: nodes.filter(n => n.type === NodeType.END) as EndNodeModel[],
        decisionTableNodes: nodes.filter(n => n.type === NodeType.TABLE) as DecisionTableNodeModel[],
        allNodes: nodes,
    };
}

// ─────────────────────────────────────────────────────────────────────────────
// Step 3 — Compute the diff between previous and new state
// ─────────────────────────────────────────────────────────────────────────────

// EndNodes now use the same diffByKey pattern as other nodes

export function getGraphDiff(
    previous: GraphPreviousState,
    current: GraphNewState
): GraphDiff {
    const allNodes = current.allNodes;

    const crewNodes = diffByKey(
        previous.crewNodes,
        current.crewNodes,
        n => n.backendId,
        getCrewNodeForComparisonFromBackend,
        getCrewNodeForComparisonFromUI,
        'CrewNode'
    );

    const pythonNodes = diffByKey(
        previous.pythonNodes,
        current.pythonNodes,
        n => n.backendId,
        getPythonNodeForComparisonFromBackend,
        getPythonNodeForComparisonFromUI,
        'PythonNode'
    );

    const llmNodes = diffByKey(
        previous.llmNodes,
        current.llmNodes,
        n => n.backendId,
        getLLMNodeForComparisonFromBackend,
        getLLMNodeForComparisonFromUI,
        'LLMNode'
    );

    const fileExtractorNodes = diffByKey(
        previous.fileExtractorNodes,
        current.fileExtractorNodes,
        n => n.backendId,
        getFileExtractorNodeForComparisonFromBackend,
        getFileExtractorNodeForComparisonFromUI,
        'FileExtractorNode'
    );

    const audioToTextNodes = diffByKey(
        previous.audioToTextNodes,
        current.audioToTextNodes,
        n => n.backendId,
        getAudioToTextNodeForComparisonFromBackend,
        getAudioToTextNodeForComparisonFromUI,
        'AudioToTextNode'
    );

    const subGraphNodes = diffByKey(
        previous.subGraphNodes,
        current.subGraphNodes,
        n => n.backendId,
        getSubGraphNodeForComparisonFromBackend,
        getSubGraphNodeForComparisonFromUI,
        'SubGraphNode'
    );

    const webhookTriggerNodes = diffByKey(
        previous.webhookTriggerNodes,
        current.webhookTriggerNodes,
        n => n.backendId,
        getWebhookTriggerNodeForComparisonFromBackend,
        getWebhookTriggerNodeForComparisonFromUI,
        'WebhookTriggerNode'
    );

    const telegramTriggerNodes = diffByKey(
        previous.telegramTriggerNodes,
        current.telegramTriggerNodes,
        n => n.backendId,
        getTelegramTriggerNodeForComparisonFromBackend,
        getTelegramTriggerNodeForComparisonFromUI,
        'TelegramTriggerNode'
    );

    const conditionalEdges = diffByKey(
        previous.conditionalEdges,
        current.conditionalEdges,
        n => n.edgeNode.backendId,
        getConditionalEdgeForComparisonFromBackend,
        getConditionalEdgeForComparisonFromUI,
        'ConditionalEdge'
    );

    const decisionTableNodes = diffByKey(
        previous.decisionTableNodes,
        current.decisionTableNodes,
        n => n.backendId,
        getDecisionTableNodeForComparisonFromBackend,
        n => getDecisionTableNodeForComparisonFromUI(n, allNodes),
        'DecisionTableNode'
    );

    // Edges: no update logic (key = start+end, so a "changed" edge is a delete+create)
    const backendEdgeMap = new Map(previous.edges.map(e => [`${e.start_key}__${e.end_key}`, e]));
    const uiEdgeKeys = new Set(current.edges.map(e => `${e.start_key}__${e.end_key}`));
    const edgesToDelete = previous.edges.filter(e => !uiEdgeKeys.has(`${e.start_key}__${e.end_key}`));
    const edgesToCreate = current.edges.filter(e => !backendEdgeMap.has(`${e.start_key}__${e.end_key}`));

    const endNodes = diffByKey(
        previous.endNodes,
        current.endNodes,
        n => n.backendId,
        getEndNodeForComparisonFromBackend,
        getEndNodeForComparisonFromUI,
        'EndNode'
    );

    const noteNodes = diffByKey(
        previous.noteNodes,
        current.noteNodes,
        n => n.backendId,
        getNoteNodeForComparisonFromBackend,
        getNoteNodeForComparisonFromUI,
        'NoteNode'
    );

    return {
        crewNodes,
        pythonNodes,
        llmNodes,
        fileExtractorNodes,
        audioToTextNodes,
        subGraphNodes,
        webhookTriggerNodes,
        telegramTriggerNodes,
        conditionalEdges,
        decisionTableNodes,
        edges: { toDelete: edgesToDelete, toCreate: edgesToCreate },
        endNodes,
        noteNodes,
    };
}

// ─────────────────────────────────────────────────────────────────────────────
// Step 4 — Payload builders (UI node → API request body)
// ─────────────────────────────────────────────────────────────────────────────

export function buildCrewPayload(n: ProjectNodeModel, graphId: number): CreateCrewNodeRequest {
    return {
        node_name: n.node_name,
        graph: graphId,
        crew_id: (n.data as GetProjectRequest).id,
        input_map: n.input_map || {},
        output_variable_path: n.output_variable_path || null,
        metadata: getUIMetadataForComparison(n),
    };
}

export function buildPythonPayload(n: PythonNodeModel, graphId: number): CreatePythonNodeRequest {
    return {
        node_name: n.node_name,
        graph: graphId,
        python_code: n.data,
        input_map: n.input_map || {},
        output_variable_path: n.output_variable_path || null,
        metadata: getUIMetadataForComparison(n),
    };
}

export function buildLLMPayload(n: LLMNodeModel, graphId: number): CreateLLMNodeRequest {
    return {
        node_name: n.node_name,
        graph: graphId,
        llm_config: n.data.id,
        input_map: n.input_map || {},
        output_variable_path: n.output_variable_path || null,
        metadata: getUIMetadataForComparison(n),
    };
}

export function buildFileExtractorPayload(n: FileExtractorNodeModel, graphId: number): CreateFileExtractorNodeRequest {
    return {
        node_name: n.node_name,
        graph: graphId,
        input_map: n.input_map || {},
        output_variable_path: n.output_variable_path || null,
        metadata: getUIMetadataForComparison(n),
    };
}

export function buildAudioToTextPayload(n: AudioToTextNodeModel, graphId: number): CreateAudioToTextNodeRequest {
    return {
        node_name: n.node_name,
        graph: graphId,
        input_map: n.input_map || {},
        output_variable_path: n.output_variable_path || null,
        metadata: getUIMetadataForComparison(n),
    };
}

export function buildSubGraphPayload(n: SubGraphNodeModel, graphId: number): CreateSubGraphNodeRequest {
    return {
        node_name: n.node_name,
        graph: graphId,
        subgraph: n.data.id,
        input_map: n.input_map || {},
        output_variable_path: n.output_variable_path || null,
        metadata: getUIMetadataForComparison(n),
    };
}

export function buildWebhookPayload(n: WebhookTriggerNodeModel, graphId: number): CreateWebhookTriggerNodeRequest {
    return {
        node_name: n.node_name,
        graph: graphId,
        python_code: n.data.python_code,
        input_map: n.input_map || {},
        output_variable_path: n.output_variable_path || null,
        webhook_trigger_path: '',
        webhook_trigger: n.data.webhook_trigger,
        metadata: getUIMetadataForComparison(n),
    };
}

export function buildTelegramPayload(n: TelegramTriggerNodeModel, graphId: number): CreateTelegramTriggerNodeRequest {
    return {
        node_name: n.node_name,
        graph: graphId,
        telegram_bot_api_key: n.data.telegram_bot_api_key,
        webhook_trigger: n.data.webhook_trigger,
        fields: n.data.fields,
        metadata: getUIMetadataForComparison(n),
    };
}

export function buildCondEdgePayload(re: ResolvedConditionalEdge, graphId: number): CreateConditionalEdgeRequest {
    return {
        graph: graphId,
        source: re.sourceName ?? '',
        then: re.targetName,
        python_code: re.edgeNode.data.python_code,
        input_map: re.edgeNode.input_map || {},
        metadata: {
            ...getUIMetadataForComparison(re.edgeNode),
            node_name: re.edgeNode.node_name,
        },
    };
}

export function buildEdgePayload(e: { start_key: string; end_key: string }, graphId: number): CreateEdgeRequest {
    return { start_key: e.start_key, end_key: e.end_key, graph: graphId };
}

export function buildEndNodePayload(n: EndNodeModel, graphId: number): CreateEndNodeRequest {
    return {
        graph: graphId,
        output_map: (n.data as any).output_map ?? { context: 'variables.context' },
        metadata: getUIMetadataForComparison(n),
    };
}

export function buildDecisionTablePayload(
    node: DecisionTableNodeModel,
    graphId: number,
    allNodes: NodeModel[]
): CreateDecisionTableNodeRequest {
    const tableData = (node as any).data?.table;

    const conditionGroups: CreateConditionGroupRequest[] = ((tableData?.condition_groups ?? []) as any[])
        .filter(g => g.valid !== false)
        .sort((a, b) => (a.order ?? Number.MAX_SAFE_INTEGER) - (b.order ?? Number.MAX_SAFE_INTEGER))
        .map((g, idx) => ({
            group_name: g.group_name,
            group_type: g.group_type ?? 'complex',
            expression: g.expression,
            conditions: (g.conditions ?? []).map((c: any) => ({
                condition_name: c.condition_name,
                condition: c.condition,
            })),
            manipulation: g.manipulation,
            next_node: resolveNodeName(g.next_node, allNodes),
            order: typeof g.order === 'number' ? g.order : idx + 1,
        }));

    return {
        graph: graphId,
        node_name: node.node_name,
        condition_groups: conditionGroups,
        default_next_node: resolveNodeName(tableData?.default_next_node, allNodes),
        next_error_node: resolveNodeName(tableData?.next_error_node, allNodes),
        metadata: getUIMetadataForComparison(node),
    };
}

export function buildNoteNodePayload(n: NoteNodeModel, graphId: number): CreateNoteNodeRequest {
    return {
        node_name: n.node_name,
        graph: graphId,
        content: n.data.content,
        metadata: {
            ...getUIMetadataForComparison(n),
            backgroundColor: n.data.backgroundColor ?? null,
        },
    };
}
