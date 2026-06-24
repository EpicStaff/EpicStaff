import { GraphDto } from '../../../features/flows/models/graph.model';
import { NodeType } from '../../core/enums/node-type';
import { FlowModel } from '../../core/models/flow.model';
import { NodeDiffByType } from './types';

export function patchFlowStateWithBackendIds(
    currentFlow: FlowModel,
    previousFlow: FlowModel,
    nodeDiff: NodeDiffByType,
    responseGraph: GraphDto
): FlowModel {
    const uiToBackendId = buildCreatedNodeIdMap(previousFlow, nodeDiff, responseGraph);
    if (uiToBackendId.size === 0) return currentFlow;

    const pythonCodeIdByBackendId = new Map<number, number | null>();
    for (const pn of responseGraph.python_node_list ?? []) {
        pythonCodeIdByBackendId.set(pn.id, pn.python_code?.id ?? null);
    }

    const scheduleDataByBackendId = new Map<
        number,
        { nextRunDateTime: string | null; isActive: boolean; currentRuns: number }
    >();
    for (const sn of responseGraph.schedule_trigger_node_list ?? []) {
        scheduleDataByBackendId.set(sn.id, {
            nextRunDateTime: sn.schedule?.next_run_date_time ?? null,
            isActive: sn.is_active,
            currentRuns: sn.current_runs,
        });
    }

    const patchedNodes = currentFlow.nodes.map((node) => {
        const mappedBackendId = uiToBackendId.get(node.id);
        let patched = mappedBackendId != null ? { ...node, backendId: mappedBackendId } : node;

        if (patched.type === NodeType.PYTHON) {
            const resolvedBackendId = mappedBackendId ?? patched.backendId;
            if (resolvedBackendId != null && pythonCodeIdByBackendId.has(resolvedBackendId)) {
                patched = { ...patched, python_code_id: pythonCodeIdByBackendId.get(resolvedBackendId) ?? null };
            }
        }

        if (patched.type === NodeType.SCHEDULE_TRIGGER) {
            const resolvedBackendId = mappedBackendId ?? patched.backendId;
            if (resolvedBackendId != null && scheduleDataByBackendId.has(resolvedBackendId)) {
                const scheduleData = scheduleDataByBackendId.get(resolvedBackendId)!;
                patched = {
                    ...patched,
                    data: {
                        ...patched.data,
                        nextRunDateTime: scheduleData.nextRunDateTime ?? patched.data.nextRunDateTime,
                        isActive: scheduleData.isActive,
                        currentRuns: scheduleData.currentRuns,
                    },
                };
            }
        }

        return patched;
    });

    const backendIdByUuid = new Map<string, number>();
    for (const node of patchedNodes) {
        if (node.backendId != null) backendIdByUuid.set(node.id, node.backendId);
    }

    const edgeByPair = new Map<string, GraphDto['edge_list'][number]>();
    for (const edge of responseGraph.edge_list ?? []) {
        edgeByPair.set(`${edge.start_node_id}__${edge.end_node_id}`, edge);
    }

    const patchedConnections = currentFlow.connections.map((connection) => {
        const sourceBackendId = backendIdByUuid.get(connection.sourceNodeId);
        const targetBackendId = backendIdByUuid.get(connection.targetNodeId);
        if (sourceBackendId == null || targetBackendId == null) return connection;

        const backendEdge = edgeByPair.get(`${sourceBackendId}__${targetBackendId}`);
        if (!backendEdge) return connection;
        return { ...connection, data: backendEdge };
    });

    return { nodes: patchedNodes, connections: patchedConnections };
}

function buildCreatedNodeIdMap(
    previousFlow: FlowModel,
    nodeDiff: NodeDiffByType,
    responseGraph: GraphDto
): Map<string, number> {
    const mapping = new Map<string, number>();

    const existingIdsByType = (type: NodeType): Set<number> =>
        new Set(
            previousFlow.nodes
                .filter((node) => node.type === type && node.backendId != null)
                .map((node) => node.backendId!)
        );

    const mapByNewIds = <T extends { id: string }, B extends { id: number }>(
        createdNodes: T[],
        backendNodes: B[],
        existingIds: Set<number>
    ) => {
        const newlyCreatedBackendNodes = backendNodes.filter((backendNode) => !existingIds.has(backendNode.id));
        createdNodes.forEach((node, index) => {
            const backendNode = newlyCreatedBackendNodes[index];
            if (backendNode) {
                mapping.set(node.id, backendNode.id);
            }
        });
    };

    const startCreated = nodeDiff.startNodes.toCreate;
    if (startCreated.length > 0) {
        const startExistingIds = existingIdsByType(NodeType.START);
        const startCandidates = (responseGraph.start_node_list ?? []).filter((node) => !startExistingIds.has(node.id));
        if (startCandidates[0]) {
            mapping.set(startCreated[0].id, startCandidates[0].id);
        }
    }

    mapByNewIds(nodeDiff.crewNodes.toCreate, responseGraph.crew_node_list ?? [], existingIdsByType(NodeType.PROJECT));
    mapByNewIds(
        nodeDiff.pythonNodes.toCreate,
        responseGraph.python_node_list ?? [],
        existingIdsByType(NodeType.PYTHON)
    );
    mapByNewIds(nodeDiff.llmNodes.toCreate, responseGraph.llm_node_list ?? [], existingIdsByType(NodeType.LLM));
    mapByNewIds(
        nodeDiff.fileExtractorNodes.toCreate,
        responseGraph.file_extractor_node_list ?? [],
        existingIdsByType(NodeType.FILE_EXTRACTOR)
    );
    mapByNewIds(
        nodeDiff.audioToTextNodes.toCreate,
        responseGraph.audio_transcription_node_list ?? [],
        existingIdsByType(NodeType.AUDIO_TO_TEXT)
    );
    mapByNewIds(
        nodeDiff.subgraphNodes.toCreate,
        responseGraph.subgraph_node_list ?? [],
        existingIdsByType(NodeType.SUBGRAPH)
    );
    mapByNewIds(
        nodeDiff.webhookNodes.toCreate,
        responseGraph.webhook_trigger_node_list ?? [],
        existingIdsByType(NodeType.WEBHOOK_TRIGGER)
    );
    mapByNewIds(
        nodeDiff.telegramNodes.toCreate,
        responseGraph.telegram_trigger_node_list ?? [],
        existingIdsByType(NodeType.TELEGRAM_TRIGGER)
    );
    mapByNewIds(
        nodeDiff.decisionTableNodes.toCreate,
        responseGraph.decision_table_node_list ?? [],
        existingIdsByType(NodeType.TABLE)
    );
    mapByNewIds(
        nodeDiff.codeAgentNodes.toCreate,
        responseGraph.code_agent_node_list ?? [],
        existingIdsByType(NodeType.CODE_AGENT)
    );
    mapByNewIds(nodeDiff.endNodes.toCreate, responseGraph.end_node_list ?? [], existingIdsByType(NodeType.END));
    mapByNewIds(nodeDiff.noteNodes.toCreate, responseGraph.graph_note_list ?? [], existingIdsByType(NodeType.NOTE));
    mapByNewIds(
        nodeDiff.scheduleNodes.toCreate,
        responseGraph.schedule_trigger_node_list ?? [],
        existingIdsByType(NodeType.SCHEDULE_TRIGGER)
    );
    mapByNewIds(
        nodeDiff.classificationDecisionTableNodes.toCreate,
        responseGraph.classification_decision_table_node_list ?? [],
        existingIdsByType(NodeType.CLASSIFICATION_TABLE)
    );

    return mapping;
}
