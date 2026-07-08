import { GraphDto } from '../../../features/flows/models/graph.model';
import { ConnectionModel } from '../../core/models/connection.model';
import { FlowModel } from '../../core/models/flow.model';
import { NodeModel } from '../../core/models/node.model';
import { mapClassificationDecisionTableToConnections } from './connections/classification-decision-table-connections.mapper';
import { mapDecisionTableToConnections } from './connections/decision-table-connections.mapper';
import { mapEdgesToConnections } from './connections/plain-edge.mapper';
import { mapAudioToTextNodeToModel } from './nodes/audio-to-text-node.mapper';
import { mapClassificationDecisionTableNodeToModel } from './nodes/classification-decision-table-node.mapper';
import { mapCodeAgentNodeToModel } from './nodes/code-agent-node.mapper';
import { mapCrewNodeToModel } from './nodes/crew-node.mapper';
import { mapDecisionTableNodeToModel } from './nodes/decision-table-node.mapper';
import { mapEndNodeToModel } from './nodes/end-node.mapper';
import { mapFileExtractorNodeToModel } from './nodes/file-extractor-node.mapper';
import { mapGraphNoteToModel } from './nodes/graph-note.mapper';
import { mapLLMNodeToModel } from './nodes/llm-node.mapper';
import { mapPythonNodeToModel } from './nodes/python-node.mapper';
import { mapScheduleTriggerNodeToModel } from './nodes/schedule-trigger-node.mapper';
import { mapStartNodeToModel } from './nodes/start-node.mapper';
import { mapSubGraphNodeToModel } from './nodes/subgraph-node.mapper';
import { mapTelegramTriggerNodeToModel } from './nodes/telegram-trigger-node.mapper';
import { mapWebhookTriggerNodeToModel } from './nodes/webhook-trigger-node.mapper';
import { resolveClassificationDecisionTableNodeRefs } from './ref-resolvers/classification-decision-table-refs';
import { resolveDecisionTableNodeRefs } from './ref-resolvers/decision-table-refs';

/**
 * Maps a backend node list to UI models, preserving temp identity: live
 * snapshot entries that are not persisted yet carry a `temp_id` (the author's
 * canvas id) instead of a DB `id`. Reusing it as the canvas id keeps node
 * identity identical across all clients, so WS refs (node_updated, edges'
 * start/end_temp_id, locks) resolve on late-joining canvases too.
 */
function mapList<R, T extends NodeModel>(raws: R[] | undefined | null, mapFn: (raw: R) => T): T[] {
    return (raws ?? []).map((raw) => {
        const tempId = (raw as { temp_id?: unknown })?.temp_id;

        const safeRaw = tempId != null && (raw as { id?: unknown })?.id == null ? { ...raw, id: 0 } : raw;
        const model = mapFn(safeRaw as R);
        return tempId ? { ...model, id: String(tempId), backendId: null } : model;
    });
}

/**
 * Reassigns colliding/missing nodeNumbers to the next free integers.
 * BE-imported nodes keep their source graph's nodeNumber, which can duplicate
 * existing ones — this guarantees a unique #N badge per node after load.
 */
function deduplicateNodeNumbers(nodes: NodeModel[]): NodeModel[] {
    const seen = new Set<number>();
    let next = Math.max(0, ...nodes.map((n) => n.nodeNumber ?? 0)) + 1;
    return nodes.map((n) => {
        if (n.nodeNumber == null || seen.has(n.nodeNumber)) {
            const num = next++;
            seen.add(num);
            return { ...n, nodeNumber: num };
        }
        seen.add(n.nodeNumber);
        return n;
    });
}

export function mapGraphDtoToFlowModel(graph: GraphDto): FlowModel {
    // ── 1. Map each backend node list to UI node models ──────────────────
    const startNodes = mapList(graph.start_node_list, mapStartNodeToModel);
    const crewNodes = mapList(graph.crew_node_list, mapCrewNodeToModel);
    const pythonNodes = mapList(graph.python_node_list, mapPythonNodeToModel);
    const llmNodes = mapList(graph.llm_node_list, mapLLMNodeToModel);
    const fileExtractorNodes = mapList(graph.file_extractor_node_list, mapFileExtractorNodeToModel);
    const audioToTextNodes = mapList(graph.audio_transcription_node_list, mapAudioToTextNodeToModel);
    const subGraphNodes = mapList(graph.subgraph_node_list, mapSubGraphNodeToModel);
    const noteNodes = mapList(graph.graph_note_list, mapGraphNoteToModel);
    const webhookTriggerNodes = mapList(graph.webhook_trigger_node_list, mapWebhookTriggerNodeToModel);
    const telegramTriggerNodes = mapList(graph.telegram_trigger_node_list, mapTelegramTriggerNodeToModel);
    const scheduleTriggerNodes = mapList(graph.schedule_trigger_node_list, mapScheduleTriggerNodeToModel);
    const endNodes = mapList(graph.end_node_list, mapEndNodeToModel);
    const codeAgentNodes = mapList(graph.code_agent_node_list, mapCodeAgentNodeToModel);
    const decisionTableNodes = mapList(graph.decision_table_node_list, mapDecisionTableNodeToModel);
    const classificationDecisionTableNodes = mapList(
        graph.classification_decision_table_node_list,
        mapClassificationDecisionTableNodeToModel
    );

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
        ...scheduleTriggerNodes,
        ...endNodes,
        ...codeAgentNodes,
        ...decisionTableNodes,
        ...classificationDecisionTableNodes,
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

    // ── 4b. Resolve CDT refs (default/error nodes + condition group next_node) ──
    resolveClassificationDecisionTableNodeRefs(
        classificationDecisionTableNodes,
        graph.classification_decision_table_node_list ?? [],
        backendIdToUuid
    );

    // ── 4c. Build nodeByUuid map for CDT connections ─────────────────────
    const nodeByUuid = new Map<string, NodeModel>();
    for (const n of allNodes) {
        nodeByUuid.set(n.id, n);
    }

    // ── 5. Map all edge lists to canvas connections ──────────────────────
    const allConnections: ConnectionModel[] = [
        ...mapEdgesToConnections(graph.edge_list ?? [], backendIdToUuid, nodeByBackendId, nodeByUuid),
        ...mapDecisionTableToConnections(
            decisionTableNodes,
            backendIdToUuid,
            nodeByBackendId,
            graph.decision_table_node_list ?? []
        ),
        ...mapClassificationDecisionTableToConnections(classificationDecisionTableNodes, nodeByUuid),
    ];

    const duplicateConnectionIds = allConnections
        .map((c) => c.id)
        .filter((id, index, arr) => arr.indexOf(id) !== index);
    if (duplicateConnectionIds.length > 0) {
        console.warn(
            `[load][duplicate-connection-ids] graphId=${graph.id} duplicateIds=${JSON.stringify(duplicateConnectionIds)}`
        );
    }

    return { nodes: deduplicateNodeNumbers(allNodes), connections: allConnections };
}
