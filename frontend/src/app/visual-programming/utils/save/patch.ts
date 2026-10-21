import { NodeType } from '@shared/models';

import { GraphDto } from '../../../features/flows/models/graph.model';
import { AgentNode, AgentNodeTaskUi } from '../../core/models/agent-node.model';
import { PromptConfig } from '../../core/models/classification-decision-table.model';
import { GetClassificationDecisionTableNodeRequest } from '../../core/models/classification-decision-table-node.model';
import { ConditionGroup } from '../../core/models/decision-table.model';
import { FlowModel } from '../../core/models/flow.model';
import { AgentNodeModel, ClassificationDecisionTableNodeModel } from '../../core/models/node.model';
import { NodeDiffByType } from './types';

/** The backend id an id-less task at `index` was given, if any. */
type AgentTaskIdResolver = (task: AgentNodeTaskUi, index: number) => number | undefined;

/** For one agent node, how its id-less tasks get their ids; null leaves its tasks as they are. */
type AgentTaskIdLookup = (node: AgentNodeModel, backendId: number | null) => AgentTaskIdResolver | null;

/**
 * Patches the flow that was SENT with what the save response assigned: node ids,
 * agent task ids, edges and the schedule-trigger fields. Agent task ids are matched
 * by position, which only the sent flow can do — the response lists a node's tasks
 * in the order they were sent.
 */
export function patchFlowStateWithBackendIds(
    sentFlow: FlowModel,
    previousFlow: FlowModel,
    nodeDiff: NodeDiffByType,
    responseGraph: GraphDto
): FlowModel {
    const agentNodeByBackendId = new Map<number, AgentNode>();
    for (const an of responseGraph.agent_node_list ?? []) {
        agentNodeByBackendId.set(an.id, an);
    }

    return patchWithBackendIds(sentFlow, previousFlow, nodeDiff, responseGraph, (_node, backendId) => {
        const responseAgentNode = backendId != null ? agentNodeByBackendId.get(backendId) : undefined;
        return responseAgentNode ? taskIdByPosition(responseAgentNode) : null;
    });
}

/**
 * The same patch for the LIVE canvas, which may have changed while the save was in
 * flight: a task inserted, removed or moved meanwhile would take another task's id by
 * position. So agent task ids are taken from `sentFlowPatched` — the sent flow, already
 * patched — and matched by `tempId`; a task added since the save gets none.
 */
export function patchLiveFlowWithBackendIds(
    liveFlow: FlowModel,
    sentFlowPatched: FlowModel,
    previousFlow: FlowModel,
    nodeDiff: NodeDiffByType,
    responseGraph: GraphDto
): FlowModel {
    const sentAgentNodes = new Map<string, AgentNodeModel>();
    for (const node of sentFlowPatched.nodes) {
        if (node.type === NodeType.AGENT) sentAgentNodes.set(node.id, node);
    }

    return patchWithBackendIds(liveFlow, previousFlow, nodeDiff, responseGraph, (node) => {
        const sentNode = sentAgentNodes.get(node.id);
        if (!sentNode) return null;
        const idByTempId = new Map<string, number>();
        for (const task of sentNode.data.tasks) {
            if (task.tempId && task.id != null) idByTempId.set(task.tempId, task.id);
        }
        return (task) => (task.tempId ? idByTempId.get(task.tempId) : undefined);
    });
}

/** New tasks' ids by position, which needs nothing else: the response's task `order` is the index as sent. */
function taskIdByPosition(responseAgentNode: AgentNode): AgentTaskIdResolver {
    const responseTasksByOrder = new Map<number, AgentNode['tasks'][number]>();
    for (const t of responseAgentNode.tasks ?? []) {
        responseTasksByOrder.set(t.order, t);
    }
    return (_task, index) => responseTasksByOrder.get(index)?.id;
}

/** Gives id-less tasks their ids, then resolves sibling `contextRefs` that named them by `tempId`. */
function applyAgentTaskIds(node: AgentNodeModel, idFor: AgentTaskIdResolver): AgentNodeModel {
    const patchedTasks = node.data.tasks.map((task, index) => {
        if (task.id != null) return task;
        const assignedId = idFor(task, index);
        return assignedId != null ? { ...task, id: assignedId } : task;
    });

    const idByTempId = new Map<string, number>();
    for (const sibling of patchedTasks) {
        if (sibling.tempId && sibling.id != null) idByTempId.set(sibling.tempId, sibling.id);
    }
    const patchedTasksWithRefs = patchedTasks.map((task) => {
        if (!task.contextRefs?.length) return task;
        let changed = false;
        const newRefs = task.contextRefs.map((ref) => {
            if (ref.id == null && ref.tempId != null) {
                const resolvedId = idByTempId.get(ref.tempId);
                if (resolvedId != null) {
                    changed = true;
                    return { id: resolvedId };
                }
            }
            return ref;
        });
        return changed ? { ...task, contextRefs: newRefs } : task;
    });

    return { ...node, data: { ...node.data, tasks: patchedTasksWithRefs } };
}

function patchWithBackendIds(
    currentFlow: FlowModel,
    previousFlow: FlowModel,
    nodeDiff: NodeDiffByType,
    responseGraph: GraphDto,
    agentTaskIds: AgentTaskIdLookup
): FlowModel {
    const uiToBackendId = buildCreatedNodeIdMap(previousFlow, nodeDiff, responseGraph);

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

        if (patched.type === NodeType.AGENT) {
            const idFor = agentTaskIds(patched, mappedBackendId ?? patched.backendId);
            if (idFor) patched = applyAgentTaskIds(patched, idFor);
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

    mapByNewIds(
        nodeDiff.pythonNodes.toCreate,
        responseGraph.python_node_list ?? [],
        existingIdsByType(NodeType.PYTHON)
    );
    mapByNewIds(nodeDiff.taskNodes.toCreate, responseGraph.task_node_list ?? [], existingIdsByType(NodeType.TASK));
    mapByNewIds(nodeDiff.agentNodes.toCreate, responseGraph.agent_node_list ?? [], existingIdsByType(NodeType.AGENT));
    mapByNewIds(
        nodeDiff.fileExtractorNodes.toCreate,
        responseGraph.file_extractor_node_list ?? [],
        existingIdsByType(NodeType.FILE_EXTRACTOR)
    );
    mapByNewIds(
        nodeDiff.keyValueNodes.toCreate,
        responseGraph.key_value_node_list ?? [],
        existingIdsByType(NodeType.KEY_VALUE)
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
    mapByNewIds(
        nodeDiff.knowledgeRetrieverNodes.toCreate,
        responseGraph.knowledge_node_list ?? [],
        existingIdsByType(NodeType.KNOWLEDGE_RETRIEVER)
    );

    return mapping;
}

export function patchCdtPromptBackendIds(flow: FlowModel, responseGraph: GraphDto): FlowModel {
    const responseByBackendId = new Map<number, GetClassificationDecisionTableNodeRequest>();
    for (const rn of responseGraph.classification_decision_table_node_list ?? []) {
        responseByBackendId.set(rn.id, rn);
    }

    if (responseByBackendId.size === 0) return flow;

    const patchedNodes = flow.nodes.map((node) => {
        if (node.type !== NodeType.CLASSIFICATION_TABLE) return node;

        const cdtNode = node as ClassificationDecisionTableNodeModel;
        if (cdtNode.backendId == null) return node;

        const responseNode = responseByBackendId.get(cdtNode.backendId);
        if (!responseNode?.prompt_configs?.length) return node;

        const backendIdByKey = new Map<string, number>();
        for (const pc of responseNode.prompt_configs) {
            backendIdByKey.set(pc.prompt_key, pc.id);
        }

        const currentPrompts = (cdtNode.data?.table?.prompts ?? {}) as Record<string, PromptConfig>;
        let promptsChanged = false;
        const updatedPrompts: Record<string, PromptConfig> = {};

        for (const [key, cfg] of Object.entries(currentPrompts)) {
            const typedCfg = cfg as PromptConfig;
            const responseBackendId = backendIdByKey.get(key);
            if (responseBackendId != null && typedCfg.backendId == null) {
                updatedPrompts[key] = { ...typedCfg, backendId: responseBackendId };
                promptsChanged = true;
            } else {
                updatedPrompts[key] = typedCfg;
            }
        }

        if (!promptsChanged) return node;

        return {
            ...cdtNode,
            data: {
                ...cdtNode.data,
                table: {
                    ...cdtNode.data?.table,
                    prompts: updatedPrompts,
                },
            },
        };
    });

    return { ...flow, nodes: patchedNodes };
}

export function buildCdtSavedBaseline(flow: FlowModel, responseGraph: GraphDto): FlowModel {
    const responseByBackendId = new Map<number, GetClassificationDecisionTableNodeRequest>();
    for (const rn of responseGraph.classification_decision_table_node_list ?? []) {
        responseByBackendId.set(rn.id, rn);
    }

    if (responseByBackendId.size === 0) return flow;

    const patchedNodes = flow.nodes.map((node) => {
        if (node.type !== NodeType.CLASSIFICATION_TABLE) return node;

        const cdtNode = node as ClassificationDecisionTableNodeModel;
        if (cdtNode.backendId == null) return node;

        const responseNode = responseByBackendId.get(cdtNode.backendId);
        if (!responseNode) return node;

        const keyById = new Map<number, string>();
        for (const pc of responseNode.prompt_configs ?? []) {
            keyById.set(pc.id, pc.prompt_key);
        }

        const currentGroups: ConditionGroup[] = cdtNode.data?.table?.condition_groups ?? [];
        let groupsChanged = false;
        const updatedGroups = currentGroups.map((g) => {
            const responseGroup = (responseNode.condition_groups ?? []).find((rg) => rg.group_name === g.group_name);
            if (!responseGroup) return g;

            const promptId = responseGroup.prompt != null ? (keyById.get(responseGroup.prompt) ?? null) : null;
            if (promptId === (g.prompt_id ?? null)) return g;
            groupsChanged = true;
            return { ...g, prompt_id: promptId };
        });

        if (!groupsChanged) return node;

        return {
            ...cdtNode,
            data: {
                ...cdtNode.data,
                table: {
                    ...cdtNode.data?.table,
                    condition_groups: updatedGroups,
                },
            },
        };
    });

    return { ...flow, nodes: patchedNodes };
}
