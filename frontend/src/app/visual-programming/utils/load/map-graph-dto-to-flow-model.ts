import { GraphDto } from '../../../features/flows/models/graph.model';
import { ConnectionModel } from '../../core/models/connection.model';
import { FlowModel } from '../../core/models/flow.model';
import { NodeModel } from '../../core/models/node.model';
import { mapDecisionTableToConnections } from './connections/decision-table-connections.mapper';
import { mapEdgesToConnections } from './connections/plain-edge.mapper';
import { mapAudioToTextNodeToModel } from './nodes/audio-to-text-node.mapper';
import { mapCodeAgentNodeToModel } from './nodes/code-agent-node.mapper';
import { mapCrewNodeToModel } from './nodes/crew-node.mapper';
import { mapDecisionTableNodeToModel } from './nodes/decision-table-node.mapper';
import { mapEndNodeToModel } from './nodes/end-node.mapper';
import { mapFileExtractorNodeToModel } from './nodes/file-extractor-node.mapper';
import { mapGraphNoteToModel } from './nodes/graph-note.mapper';
import { mapLLMNodeToModel } from './nodes/llm-node.mapper';
import { mapPythonNodeToModel } from './nodes/python-node.mapper';
import { mapStartNodeToModel } from './nodes/start-node.mapper';
import { mapSubGraphNodeToModel } from './nodes/subgraph-node.mapper';
import { mapTelegramTriggerNodeToModel } from './nodes/telegram-trigger-node.mapper';
import { mapWebhookTriggerNodeToModel } from './nodes/webhook-trigger-node.mapper';
import { resolveDecisionTableNodeRefs } from './ref-resolvers/decision-table-refs';

export function mapGraphDtoToFlowModel(graph: GraphDto): FlowModel {
    // ── 1. Map each backend node list to UI node models ──────────────────
    const startNodes = (graph.start_node_list ?? []).map((n) => mapStartNodeToModel(n));
    const crewNodes = (graph.crew_node_list ?? []).map((n) => mapCrewNodeToModel(n));
    const pythonNodes = (graph.python_node_list ?? []).map((n) => mapPythonNodeToModel(n));
    const llmNodes = (graph.llm_node_list ?? []).map((n) => mapLLMNodeToModel(n));
    const fileExtractorNodes = (graph.file_extractor_node_list ?? []).map((n) => mapFileExtractorNodeToModel(n));
    const audioToTextNodes = (graph.audio_transcription_node_list ?? []).map((n) => mapAudioToTextNodeToModel(n));
    const subGraphNodes = (graph.subgraph_node_list ?? []).map((n) => mapSubGraphNodeToModel(n));
    const noteNodes = (graph.graph_note_list ?? []).map((n) => mapGraphNoteToModel(n));
    const webhookTriggerNodes = (graph.webhook_trigger_node_list ?? []).map((n) => mapWebhookTriggerNodeToModel(n));
    const telegramTriggerNodes = (graph.telegram_trigger_node_list ?? []).map((n) => mapTelegramTriggerNodeToModel(n));
    const endNodes = (graph.end_node_list ?? []).map((n) => mapEndNodeToModel(n));
    const codeAgentNodes = (graph.code_agent_node_list ?? []).map((n) => mapCodeAgentNodeToModel(n));
    const decisionTableNodes = (graph.decision_table_node_list ?? []).map((n) => mapDecisionTableNodeToModel(n));

    // ── 2. Combine into one flat node list ───────────────────────────────
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
    ];

    // ── 3. Build backendId ↔ UUID lookup maps ────────────────────────────
    const backendIdToUuid = new Map<number, string>();
    const nodeByBackendId = new Map<number, NodeModel>();
    for (const n of allNodes) {
        if (n.backendId != null) {
            if (backendIdToUuid.has(n.backendId)) {
                const existing = nodeByBackendId.get(n.backendId);
                console.warn(
                    `[load] backendId collision: ${n.backendId} — "${n.node_name}" (${n.type}) ` +
                        `vs "${existing?.node_name}" (${existing?.type})`
                );
            }
            backendIdToUuid.set(n.backendId, n.id);
            nodeByBackendId.set(n.backendId, n);
        }
    }

    // ── 4. Patch DT node data: replace backend integer refs with UUIDs ───
    resolveDecisionTableNodeRefs(decisionTableNodes, graph.decision_table_node_list ?? [], backendIdToUuid);

    // ── 5. Map all edge lists to canvas connections ──────────────────────
    const allConnections: ConnectionModel[] = [
        ...mapEdgesToConnections(graph.edge_list ?? [], backendIdToUuid, nodeByBackendId),
        ...mapDecisionTableToConnections(
            decisionTableNodes,
            backendIdToUuid,
            nodeByBackendId,
            graph.decision_table_node_list ?? []
        ),
    ];

    const duplicateConnectionIds = allConnections
        .map((c) => c.id)
        .filter((id, index, arr) => arr.indexOf(id) !== index);
    if (duplicateConnectionIds.length > 0) {
        console.warn(
            `[load][duplicate-connection-ids] graphId=${graph.id} duplicateIds=${JSON.stringify(duplicateConnectionIds)}`
        );
    }

    return { nodes: allNodes, connections: allConnections };
}
