import { NodeType } from '../../core/enums/node-type';
import { PromptConfig } from '../../core/models/classification-decision-table.model';
import { ConnectionModel } from '../../core/models/connection.model';
import { FlowModel } from '../../core/models/flow.model';
import {
    AudioToTextNodeModel,
    ClassificationDecisionTableNodeModel,
    CodeAgentNodeModel,
    DecisionTableNodeModel,
    EndNodeModel,
    FileExtractorNodeModel,
    GraphNoteModel,
    LLMNodeModel,
    NodeModel,
    ProjectNodeModel,
    PythonNodeModel,
    ScheduleTriggerNodeModel,
    StartNodeModel,
    SubGraphNodeModel,
    TelegramTriggerNodeModel,
    WebhookTriggerNodeModel,
} from '../../core/models/node.model';
import { hasPersistedWaypoints, waypointsChanged } from './edge-waypoints.helpers';
import { toNodeMetadata } from './metadata';
import { ConnectionDiff, NodeDiff, NodeDiffByType } from './types';

function areEqual(left: unknown, right: unknown): boolean {
    return JSON.stringify(left) === JSON.stringify(right);
}

export function buildUuidToBackendIdMap(nodes: NodeModel[]): Map<string, number> {
    const map = new Map<string, number>();
    for (const node of nodes) {
        if (node.backendId != null) map.set(node.id, node.backendId);
    }
    return map;
}

function nodesByType<T extends NodeModel>(nodes: NodeModel[], type: NodeType): T[] {
    return nodes.filter((node) => node.type === type) as T[];
}

function diffNodesByBackendId<T extends { backendId: number | null }>(
    previous: T[],
    current: T[],
    toComparable: (node: T) => unknown
): NodeDiff<T> {
    const previousByBackendId = new Map<number, T>();
    for (const node of previous) {
        if (node.backendId != null) previousByBackendId.set(node.backendId, node);
    }

    const toCreate: T[] = [];
    const toUpdate: Array<{ previous: T; current: T }> = [];
    const matchedBackendIds = new Set<number>();

    for (const node of current) {
        if (node.backendId == null) {
            toCreate.push(node);
            continue;
        }
        const previousNode = previousByBackendId.get(node.backendId);
        if (!previousNode) {
            toCreate.push(node);
            continue;
        }

        matchedBackendIds.add(node.backendId);
        if (!areEqual(toComparable(previousNode), toComparable(node))) {
            toUpdate.push({ previous: previousNode, current: node });
        }
    }

    const toDelete: T[] = [];
    for (const [backendId, previousNode] of previousByBackendId) {
        if (!matchedBackendIds.has(backendId)) toDelete.push(previousNode);
    }

    return { toCreate, toUpdate, toDelete };
}

function toDecisionTableComparable(node: DecisionTableNodeModel, allNodes: NodeModel[]): unknown {
    const resolveComparableNodeRef = (uuid: string | null): number | `temp:${string}` | null => {
        if (!uuid) return null;
        const backendId = allNodes.find((candidate) => candidate.id === uuid)?.backendId ?? null;
        return backendId != null ? backendId : (`temp:${uuid}` as const);
    };

    return {
        node_name: node.node_name,
        condition_groups: node.data.table.condition_groups
            .filter((group) => group.valid !== false)
            .sort((a, b) => (a.order ?? Number.MAX_SAFE_INTEGER) - (b.order ?? Number.MAX_SAFE_INTEGER))
            .map((group, index) => ({
                group_name: group.group_name,
                group_type: group.group_type,
                expression: group.expression,
                conditions: group.conditions.map((condition) => ({
                    condition_name: condition.condition_name,
                    condition: condition.condition,
                })),
                manipulation: group.manipulation,
                next_node_id: resolveComparableNodeRef(group.next_node),
                order: typeof group.order === 'number' ? group.order : index + 1,
            })),
        default_next_node_id: resolveComparableNodeRef(node.data.table.default_next_node),
        next_error_node_id: resolveComparableNodeRef(node.data.table.next_error_node),
        metadata: toNodeMetadata(node),
    };
}

function toStartComparable(node: StartNodeModel): unknown {
    return { variables: node.data.initialState ?? {}, metadata: toNodeMetadata(node) };
}

function toCrewComparable(node: ProjectNodeModel): unknown {
    return {
        node_name: node.node_name,
        crew_id: node.data.id,
        input_map: node.input_map || {},
        output_variable_path: node.output_variable_path || null,
        stream_config: node.stream_config ?? {},
        metadata: toNodeMetadata(node),
    };
}

function toPythonComparable(node: PythonNodeModel): unknown {
    return {
        node_name: node.node_name,
        python_code: node.data,
        input_map: node.input_map || {},
        output_variable_path: node.output_variable_path || null,
        stream_config: node.stream_config ?? {},
        test_input: node.test_input ?? {},
        metadata: toNodeMetadata(node),
    };
}

function toLlmComparable(node: LLMNodeModel): unknown {
    return {
        node_name: node.node_name,
        llm_config: node.data.id,
        input_map: node.input_map || {},
        output_variable_path: node.output_variable_path || null,
        metadata: toNodeMetadata(node),
    };
}

function toFileExtractorComparable(node: FileExtractorNodeModel): unknown {
    return {
        node_name: node.node_name,
        input_map: node.input_map || {},
        output_variable_path: node.output_variable_path || null,
        metadata: toNodeMetadata(node),
    };
}

function toAudioToTextComparable(node: AudioToTextNodeModel): unknown {
    return {
        node_name: node.node_name,
        input_map: node.input_map || {},
        output_variable_path: node.output_variable_path || null,
        metadata: toNodeMetadata(node),
    };
}

function toEndComparable(node: EndNodeModel): unknown {
    return {
        output_map: node.data.output_map ?? { context: 'variables.context' },
        metadata: toNodeMetadata(node),
    };
}

function toSubgraphComparable(node: SubGraphNodeModel): unknown {
    return {
        node_name: node.node_name,
        subgraph: node.data.id,
        input_map: node.input_map || {},
        output_variable_path: node.output_variable_path || null,
        metadata: toNodeMetadata(node),
    };
}

function toWebhookComparable(node: WebhookTriggerNodeModel): unknown {
    return {
        node_name: node.node_name,
        python_code: node.data.python_code,
        input_map: node.input_map || {},
        output_variable_path: node.output_variable_path || null,
        webhook_trigger_path: '',
        webhook_trigger: node.data.webhook_trigger,
        metadata: toNodeMetadata(node),
    };
}

function toTelegramComparable(node: TelegramTriggerNodeModel): unknown {
    return {
        node_name: node.node_name,
        telegram_bot_api_key: node.data.telegram_bot_api_key,
        webhook_trigger: node.data.webhook_trigger,
        fields: node.data.fields,
        metadata: toNodeMetadata(node),
    };
}

function toScheduleComparable(node: ScheduleTriggerNodeModel): unknown {
    return {
        node_name: node.node_name,
        isActive: node.data.isActive,
        runMode: node.data.runMode,
        startDateTime: node.data.startDateTime,
        intervalEvery: node.data.intervalEvery,
        intervalUnit: node.data.intervalUnit,
        weekdays: node.data.weekdays,
        endType: node.data.endType,
        endDateTime: node.data.endDateTime,
        maxRuns: node.data.maxRuns,
        timezone: node.data.timezone,
        // currentRuns is excluded: it is a read-only backend counter, not user-configurable.
        // Including it would mark nodes as dirty after every server response.
        metadata: toNodeMetadata(node),
    };
}

function toNoteComparable(node: GraphNoteModel): unknown {
    return {
        node_name: node.node_name,
        content: node.data.content,
        metadata: { ...toNodeMetadata(node), backgroundColor: node.data.backgroundColor ?? null },
    };
}

function toCodeAgentComparable(node: CodeAgentNodeModel): unknown {
    return {
        node_name: node.node_name,
        llm_config: node.data?.llm_config_id ?? null,
        agent_mode: node.data?.agent_mode ?? 'code_interpreter',
        session_id: node.data?.session_id ?? '',
        system_prompt: node.data?.system_prompt ?? '',
        stream_handler_code: node.data?.stream_handler_code ?? '',
        libraries: node.data?.libraries ?? [],
        polling_interval_ms: node.data?.polling_interval_ms ?? 100,
        silence_indicator_s: node.data?.silence_indicator_s ?? 3,
        indicator_repeat_s: node.data?.indicator_repeat_s ?? 5,
        chunk_timeout_s: node.data?.chunk_timeout_s ?? 30,
        inactivity_timeout_s: node.data?.inactivity_timeout_s ?? 120,
        max_wait_s: node.data?.max_wait_s ?? 300,
        input_map: node.input_map,
        output_variable_path: node.output_variable_path,
        stream_config: node.stream_config ?? {},
        output_schema: node.data?.output_schema ?? {},
        use_storage: node.data?.use_storage ?? false,
        metadata: toNodeMetadata(node),
    };
}

interface CdtConditionGroupUi {
    group_name: string;
    order?: number;
    expression?: string | null;
    prompt_id?: string | null;
    manipulation?: string | null;
    continue_flag?: boolean;
    continue?: boolean;
    route_code?: string | null;
    next_node?: string | null;
    dock_visible?: boolean;
    field_expressions?: Record<string, unknown>;
    field_manipulations?: Record<string, unknown>;
    section?: string | null;
}

function toCdtComparable(node: ClassificationDecisionTableNodeModel, allNodes: NodeModel[]): unknown {
    const tableData = node.data?.table;
    const resolveRef = (uuid: string | null): number | `temp:${string}` | null => {
        if (!uuid) return null;
        const backendId = allNodes.find((n) => n.id === uuid)?.backendId ?? null;
        return backendId != null ? backendId : (`temp:${uuid}` as const);
    };

    const preCode = tableData?.pre_computation?.code || tableData?.pre_computation_code || null;
    const postCode = tableData?.post_computation?.code || tableData?.post_computation_code || null;

    return {
        node_name: node.node_name,
        pre_computation_code: preCode,
        condition_groups: ((tableData?.condition_groups || []) as CdtConditionGroupUi[])
            .sort((a, b) => (a.order ?? Number.MAX_SAFE_INTEGER) - (b.order ?? Number.MAX_SAFE_INTEGER))
            .map((g, idx) => ({
                group_name: g.group_name,
                order: typeof g.order === 'number' ? g.order : idx + 1,
                expression: g.expression || null,
                prompt_id: g.prompt_id || null,
                manipulation: g.manipulation || null,
                continue_flag: !!(g.continue_flag ?? g.continue),
                route_code: g.route_code || null,
                section: g.section ?? null,
                next_node_id: resolveRef(g.next_node ?? null),
                dock_visible: g.dock_visible !== false,
                field_expressions: g.field_expressions || {},
                field_manipulations: (g.field_manipulations || {}) as Record<string, string>,
            })),
        prompt_configs: Object.entries((tableData?.prompts || {}) as Record<string, PromptConfig>)
            .sort(([a], [b]) => a.localeCompare(b))
            .map(([key, cfg]) => ({
                prompt_key: key,
                prompt_text: cfg.prompt_text ?? '',
                llm_config: cfg.llm_config ?? null,
                output_schema: cfg.output_schema ?? null,
                result_variable: cfg.result_variable ?? '',
                variable_mappings: cfg.variable_mappings ?? {},
            })),
        default_llm_config: tableData?.default_llm_config ?? null,
        default_next_node: tableData?.default_next_node || null,
        next_error_node: tableData?.next_error_node || null,
        pre_input_map: tableData?.pre_computation?.input_map || tableData?.pre_input_map || {},
        pre_output_variable_path:
            tableData?.pre_computation?.output_variable_path || tableData?.pre_output_variable_path || null,
        post_computation_code: postCode,
        post_input_map: tableData?.post_computation?.input_map || tableData?.post_input_map || {},
        post_output_variable_path:
            tableData?.post_computation?.output_variable_path || tableData?.post_output_variable_path || null,
        pre_libraries: tableData?.pre_computation?.libraries || [],
        post_libraries: tableData?.post_computation?.libraries || [],
        metadata: toNodeMetadata(node),
    };
}

export function getNodeDiff(previous: FlowModel, current: FlowModel): NodeDiffByType {
    return {
        startNodes: diffNodesByBackendId(
            nodesByType<StartNodeModel>(previous.nodes, NodeType.START),
            nodesByType<StartNodeModel>(current.nodes, NodeType.START),
            toStartComparable
        ),
        crewNodes: diffNodesByBackendId(
            nodesByType<ProjectNodeModel>(previous.nodes, NodeType.PROJECT),
            nodesByType<ProjectNodeModel>(current.nodes, NodeType.PROJECT),
            toCrewComparable
        ),
        pythonNodes: diffNodesByBackendId(
            nodesByType<PythonNodeModel>(previous.nodes, NodeType.PYTHON),
            nodesByType<PythonNodeModel>(current.nodes, NodeType.PYTHON),
            toPythonComparable
        ),
        llmNodes: diffNodesByBackendId(
            nodesByType<LLMNodeModel>(previous.nodes, NodeType.LLM),
            nodesByType<LLMNodeModel>(current.nodes, NodeType.LLM),
            toLlmComparable
        ),
        fileExtractorNodes: diffNodesByBackendId(
            nodesByType<FileExtractorNodeModel>(previous.nodes, NodeType.FILE_EXTRACTOR),
            nodesByType<FileExtractorNodeModel>(current.nodes, NodeType.FILE_EXTRACTOR),
            toFileExtractorComparable
        ),
        audioToTextNodes: diffNodesByBackendId(
            nodesByType<AudioToTextNodeModel>(previous.nodes, NodeType.AUDIO_TO_TEXT),
            nodesByType<AudioToTextNodeModel>(current.nodes, NodeType.AUDIO_TO_TEXT),
            toAudioToTextComparable
        ),
        endNodes: diffNodesByBackendId(
            nodesByType<EndNodeModel>(previous.nodes, NodeType.END),
            nodesByType<EndNodeModel>(current.nodes, NodeType.END),
            toEndComparable
        ),
        subgraphNodes: diffNodesByBackendId(
            nodesByType<SubGraphNodeModel>(previous.nodes, NodeType.SUBGRAPH),
            nodesByType<SubGraphNodeModel>(current.nodes, NodeType.SUBGRAPH),
            toSubgraphComparable
        ),
        webhookNodes: diffNodesByBackendId(
            nodesByType<WebhookTriggerNodeModel>(previous.nodes, NodeType.WEBHOOK_TRIGGER),
            nodesByType<WebhookTriggerNodeModel>(current.nodes, NodeType.WEBHOOK_TRIGGER),
            toWebhookComparable
        ),
        telegramNodes: diffNodesByBackendId(
            nodesByType<TelegramTriggerNodeModel>(previous.nodes, NodeType.TELEGRAM_TRIGGER),
            nodesByType<TelegramTriggerNodeModel>(current.nodes, NodeType.TELEGRAM_TRIGGER),
            toTelegramComparable
        ),
        scheduleNodes: diffNodesByBackendId(
            nodesByType<ScheduleTriggerNodeModel>(previous.nodes, NodeType.SCHEDULE_TRIGGER),
            nodesByType<ScheduleTriggerNodeModel>(current.nodes, NodeType.SCHEDULE_TRIGGER),
            toScheduleComparable
        ),
        decisionTableNodes: diffNodesByBackendId(
            nodesByType<DecisionTableNodeModel>(previous.nodes, NodeType.TABLE),
            nodesByType<DecisionTableNodeModel>(current.nodes, NodeType.TABLE),
            (n) => toDecisionTableComparable(n, current.nodes)
        ),
        noteNodes: diffNodesByBackendId(
            nodesByType<GraphNoteModel>(previous.nodes, NodeType.NOTE),
            nodesByType<GraphNoteModel>(current.nodes, NodeType.NOTE),
            toNoteComparable
        ),
        codeAgentNodes: diffNodesByBackendId(
            nodesByType<CodeAgentNodeModel>(previous.nodes, NodeType.CODE_AGENT),
            nodesByType<CodeAgentNodeModel>(current.nodes, NodeType.CODE_AGENT),
            toCodeAgentComparable
        ),
        classificationDecisionTableNodes: diffNodesByBackendId(
            nodesByType<ClassificationDecisionTableNodeModel>(previous.nodes, NodeType.CLASSIFICATION_TABLE),
            nodesByType<ClassificationDecisionTableNodeModel>(current.nodes, NodeType.CLASSIFICATION_TABLE),
            (n) => toCdtComparable(n, current.nodes)
        ),
    };
}

function getPlainConnections(flow: FlowModel): ConnectionModel[] {
    const nodeById = new Map(flow.nodes.map((node) => [node.id, node]));
    return flow.connections.filter((conn) => {
        const source = nodeById.get(conn.sourceNodeId);
        const target = nodeById.get(conn.targetNodeId);
        if (!source || !target) return false;
        if (
            source.type === NodeType.TABLE ||
            source.type === NodeType.CLASSIFICATION_TABLE ||
            source.type === NodeType.EDGE
        )
            return false;
        if (target.type === NodeType.EDGE) return false;
        return true;
    });
}

export function getConnectionDiff(previous: FlowModel, current: FlowModel, idMap: Map<string, number>): ConnectionDiff {
    const prevEdges = getPlainConnections(previous);
    const currEdges = getPlainConnections(current);
    const prevNodeIdMap = buildUuidToBackendIdMap(previous.nodes);
    const toNodeRefKey = (backendId: number | undefined, nodeUuid: string): string =>
        backendId != null ? String(backendId) : nodeUuid;

    const prevByKey = new Map<string, ConnectionModel>();
    for (const conn of prevEdges) {
        const source = prevNodeIdMap.get(conn.sourceNodeId);
        const target = prevNodeIdMap.get(conn.targetNodeId);
        if (source != null && target != null) {
            prevByKey.set(
                `${toNodeRefKey(source, conn.sourceNodeId)}__${toNodeRefKey(target, conn.targetNodeId)}`,
                conn
            );
        }
    }

    const currByKey = new Map<string, ConnectionModel>();
    for (const conn of currEdges) {
        const source = idMap.get(conn.sourceNodeId);
        const target = idMap.get(conn.targetNodeId);
        currByKey.set(`${toNodeRefKey(source, conn.sourceNodeId)}__${toNodeRefKey(target, conn.targetNodeId)}`, conn);
    }

    const toDelete: ConnectionModel[] = [];
    for (const [key, conn] of prevByKey) {
        if (!currByKey.has(key)) toDelete.push(conn);
    }

    const toCreate: ConnectionModel[] = [];
    for (const [key, conn] of currByKey) {
        if (!prevByKey.has(key)) toCreate.push(conn);
    }

    const toUpdate: ConnectionModel[] = [];
    for (const [key, currConn] of currByKey) {
        const prevConn = prevByKey.get(key);
        if (!prevConn || currConn.data?.id == null) continue;
        if (!hasPersistedWaypoints(currConn) && !hasPersistedWaypoints(prevConn)) continue;
        if (waypointsChanged(prevConn.waypoints, currConn.waypoints)) {
            toUpdate.push(currConn);
        }
    }

    return { toCreate, toDelete, toUpdate };
}
