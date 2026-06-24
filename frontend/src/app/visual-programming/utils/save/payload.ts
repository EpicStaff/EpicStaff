import {
    CreateClassificationDecisionTableNodeRequest,
    CreatePromptConfigRequest,
} from '../../../pages/flows-page/components/flow-visual-programming/models/classification-decision-table-node.model';
import {
    CreateConditionGroupRequest,
    CreateDecisionTableNodeRequest,
} from '../../../pages/flows-page/components/flow-visual-programming/models/decision-table-node.model';
import { PromptConfig } from '../../core/models/classification-decision-table.model';
import { ConnectionModel } from '../../core/models/connection.model';
import { FlowModel } from '../../core/models/flow.model';
import {
    ClassificationDecisionTableNodeModel,
    DecisionTableNodeModel,
    NodeModel,
    ScheduleTriggerNodeModel,
} from '../../core/models/node.model';
import { hasPersistedWaypoints, mergeWaypointsIntoMetadata } from './edge-waypoints.helpers';
import { toNodeMetadata } from './metadata';
import { ConnectionDiff, NodeDiff, NodeDiffByType } from './types';

function resolveNodeRef(
    uuid: string | null,
    allNodes: NodeModel[],
    idMap: Map<string, number>
): { backendId: number | null; tempId: string | null } {
    if (!uuid) return { backendId: null, tempId: null };
    const fromMap = idMap.get(uuid);
    if (fromMap != null) return { backendId: fromMap, tempId: null };
    const fromNode = allNodes.find((node) => node.id === uuid)?.backendId ?? null;
    return fromNode != null ? { backendId: fromNode, tempId: null } : { backendId: null, tempId: uuid };
}

function buildDecisionTableNodePayload(
    node: DecisionTableNodeModel,
    graphId: number,
    allNodes: NodeModel[],
    idMap: Map<string, number>
): Record<string, unknown> {
    const tableData = node.data.table;
    const conditionGroups: Array<CreateConditionGroupRequest & Record<string, unknown>> = tableData.condition_groups
        .filter((group) => group.valid !== false)
        .sort((a, b) => (a.order ?? Number.MAX_SAFE_INTEGER) - (b.order ?? Number.MAX_SAFE_INTEGER))
        .map((group, index) => {
            const resolved = resolveNodeRef(group.next_node, allNodes, idMap);
            return {
                group_name: group.group_name,
                group_type: group.group_type,
                expression: group.expression,
                conditions: group.conditions.map((condition) => ({
                    condition_name: condition.condition_name,
                    condition: condition.condition,
                })),
                manipulation: group.manipulation,
                next_node_id: resolved.backendId,
                ...(resolved.tempId ? { next_node_temp_id: resolved.tempId } : {}),
                order: typeof group.order === 'number' ? group.order : index + 1,
            };
        });

    const defaultNext = resolveNodeRef(tableData.default_next_node, allNodes, idMap);
    const nextError = resolveNodeRef(tableData.next_error_node, allNodes, idMap);

    return {
        graph: graphId,
        node_name: node.node_name,
        condition_groups: conditionGroups,
        default_next_node_id: defaultNext.backendId,
        ...(defaultNext.tempId ? { default_next_node_temp_id: defaultNext.tempId } : {}),
        next_error_node_id: nextError.backendId,
        ...(nextError.tempId ? { next_error_node_temp_id: nextError.tempId } : {}),
        metadata: toNodeMetadata(node),
    } satisfies CreateDecisionTableNodeRequest & Record<string, unknown>;
}

function buildScheduleBlock(node: ScheduleTriggerNodeModel): Record<string, unknown> {
    const d = node.data;

    if (d.runMode === 'once') {
        return {
            run_mode: 'once',
            start_date_time: d.startDateTime,
            interval: null,
            end: { type: 'never', date_time: null, max_runs: null },
            timezone: d.timezone,
        };
    }

    const unitAllowsWeekdays = d.intervalUnit === 'days' || d.intervalUnit === 'weeks';
    const interval = {
        every: d.intervalEvery,
        unit: d.intervalUnit,
        weekdays: unitAllowsWeekdays ? d.weekdays : [],
    };

    let end: Record<string, unknown>;
    if (d.endType === 'on_date') {
        end = { type: 'on_date', date_time: d.endDateTime, max_runs: null };
    } else if (d.endType === 'after_n_runs') {
        end = { type: 'after_n_runs', date_time: null, max_runs: d.maxRuns };
    } else {
        end = { type: 'never', date_time: null, max_runs: null };
    }

    return { run_mode: 'repeat', start_date_time: d.startDateTime, interval, end, timezone: d.timezone };
}

function serializeCDTFieldExpressions(fieldExpressions: Record<string, unknown>): Record<string, string> {
    const result: Record<string, string> = {};
    for (const [key, value] of Object.entries(fieldExpressions)) {
        if (typeof value === 'object' && value !== null && 'operator' in value) {
            const expr = value as { field?: string; operator?: string; value?: unknown };
            const field = expr.field || key;
            const op = expr.operator || '==';
            const val = expr.value;
            result[field] = typeof val === 'string' ? `${op} "${val}"` : `${op} ${val}`;
        } else {
            result[key] = String(value);
        }
    }
    return result;
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

function buildCdtNodePayload(
    node: ClassificationDecisionTableNodeModel,
    graphId: number,
    allNodes: NodeModel[],
    idMap: Map<string, number>,
    connections: ConnectionModel[]
): Record<string, unknown> {
    const tableData = node.data?.table;
    const preComp = tableData?.pre_computation || {};
    const postComp = tableData?.post_computation || {};
    const preCodeValue = preComp.code || tableData?.pre_computation_code || '';
    const postCodeValue = postComp.code || tableData?.post_computation_code || '';

    const conditionGroups = ((tableData?.condition_groups || []) as CdtConditionGroupUi[])
        .sort((a, b) => (a.order ?? Number.MAX_SAFE_INTEGER) - (b.order ?? Number.MAX_SAFE_INTEGER))
        .map((g, idx) => {
            // Resolve next_node only when route_code is present.
            let targetUuid: string | null = null;
            if (g.route_code) {
                targetUuid = g.next_node ?? null;
                if (!targetUuid) {
                    const slugified = g.route_code.toLowerCase().replace(/\s+/g, '-');
                    const routePortId = `${node.id}_decision-route-${slugified}`;
                    const conn = connections.find((c) => c.sourceNodeId === node.id && c.sourcePortId === routePortId);
                    if (conn) targetUuid = conn.targetNodeId;
                }
            }

            const resolved = resolveNodeRef(targetUuid, allNodes, idMap);

            return {
                group_name: g.group_name,
                order: typeof g.order === 'number' ? g.order : idx + 1,
                expression: g.expression || null,
                prompt_id: g.prompt_id || null,
                manipulation: g.manipulation || null,
                continue_flag: !!(g.continue_flag ?? g.continue),
                route_code: g.route_code || null,
                section: g.section ?? null,
                next_node_id: resolved.backendId,
                ...(resolved.tempId ? { next_node_temp_id: resolved.tempId } : {}),
                dock_visible: g.dock_visible !== false,
                field_expressions: serializeCDTFieldExpressions(g.field_expressions || {}),
                field_manipulations: (g.field_manipulations || {}) as Record<string, string>,
            };
        });

    let defaultTargetUuid: string | null = tableData?.default_next_node ?? null;
    if (!defaultTargetUuid) {
        const conn = connections.find(
            (c) => c.sourceNodeId === node.id && c.sourcePortId === `${node.id}_decision-default`
        );
        if (conn) defaultTargetUuid = conn.targetNodeId;
    }

    let errorTargetUuid: string | null = tableData?.next_error_node ?? null;
    if (!errorTargetUuid) {
        const conn = connections.find(
            (c) => c.sourceNodeId === node.id && c.sourcePortId === `${node.id}_decision-error`
        );
        if (conn) errorTargetUuid = conn.targetNodeId;
    }

    const defaultRef = resolveNodeRef(defaultTargetUuid, allNodes, idMap);
    const errorRef = resolveNodeRef(errorTargetUuid, allNodes, idMap);

    return {
        graph: graphId,
        node_name: node.node_name,
        pre_python_code:
            preCodeValue.trim() === ''
                ? null
                : {
                      code: preCodeValue,
                      libraries: preComp.libraries || [],
                      entrypoint: 'main',
                      global_kwargs: {},
                  },
        pre_input_map: preComp.input_map || tableData?.pre_input_map || {},
        pre_output_variable_path: preComp.output_variable_path || tableData?.pre_output_variable_path || null,
        post_python_code:
            postCodeValue.trim() === ''
                ? null
                : {
                      code: postCodeValue,
                      libraries: postComp.libraries || [],
                      entrypoint: 'main',
                      global_kwargs: {},
                  },
        post_input_map: postComp.input_map || tableData?.post_input_map || {},
        post_output_variable_path: postComp.output_variable_path || tableData?.post_output_variable_path || null,
        prompt_configs: Object.entries((tableData?.prompts || {}) as Record<string, PromptConfig>).map(
            ([key, cfg]) =>
                ({
                    prompt_key: key,
                    prompt_text: cfg.prompt_text ?? '',
                    llm_config: cfg.llm_config ?? null,
                    output_schema: cfg.output_schema ?? {},
                    result_variable: cfg.result_variable ?? '',
                    variable_mappings: cfg.variable_mappings ?? {},
                }) satisfies CreatePromptConfigRequest
        ),
        default_llm_config: tableData?.default_llm_config ?? null,
        ...(defaultRef.backendId != null ? { default_next_node_id: defaultRef.backendId } : {}),
        ...(defaultRef.tempId != null ? { default_next_node_temp_id: defaultRef.tempId } : {}),
        ...(errorRef.backendId != null ? { next_error_node_id: errorRef.backendId } : {}),
        ...(errorRef.tempId != null ? { next_error_node_temp_id: errorRef.tempId } : {}),
        condition_groups: conditionGroups,
        metadata: toNodeMetadata(node),
    } satisfies CreateClassificationDecisionTableNodeRequest & Record<string, unknown>;
}

export function buildBulkSavePayload(
    graphId: number,
    nodeDiff: NodeDiffByType,
    connectionDiff: ConnectionDiff,
    current: FlowModel,
    idMap: Map<string, number>,
    saveVersion: number
): Record<string, unknown> {
    const nodeItems = <T extends { id: string; backendId: number | null }>(
        diff: NodeDiff<T>,
        mapPayload: (node: T) => Record<string, unknown>
    ) => [
        ...diff.toCreate.map((node) => ({ id: null, temp_id: node.id, ...mapPayload(node) })),
        ...diff.toUpdate.map(({ current: node }) => ({ id: node.backendId, ...mapPayload(node) })),
    ];

    const edgeList = connectionDiff.toCreate.map((conn: ConnectionModel) => {
        const startNodeId = idMap.get(conn.sourceNodeId);
        const endNodeId = idMap.get(conn.targetNodeId);
        return {
            graph: graphId,
            ...(startNodeId != null ? { start_node_id: startNodeId } : { start_temp_id: conn.sourceNodeId }),
            ...(endNodeId != null ? { end_node_id: endNodeId } : { end_temp_id: conn.targetNodeId }),
            ...(hasPersistedWaypoints(conn)
                ? { metadata: mergeWaypointsIntoMetadata(conn.data?.metadata ?? {}, conn.waypoints!) }
                : {}),
        };
    });

    const edgeUpdateList = connectionDiff.toUpdate.map((conn: ConnectionModel) => {
        const startNodeId = idMap.get(conn.sourceNodeId);
        const endNodeId = idMap.get(conn.targetNodeId);
        return {
            id: conn.data!.id,
            graph: graphId,
            ...(startNodeId != null ? { start_node_id: startNodeId } : { start_temp_id: conn.sourceNodeId }),
            ...(endNodeId != null ? { end_node_id: endNodeId } : { end_temp_id: conn.targetNodeId }),
            metadata: mergeWaypointsIntoMetadata(conn.data?.metadata ?? {}, conn.waypoints ?? []),
        };
    });

    const deleted = {
        start_node_ids: nodeDiff.startNodes.toDelete.map((n) => n.backendId!).filter((id) => id != null),
        crew_node_ids: nodeDiff.crewNodes.toDelete.map((n) => n.backendId!).filter((id) => id != null),
        python_node_ids: nodeDiff.pythonNodes.toDelete.map((n) => n.backendId!).filter((id) => id != null),
        llm_node_ids: nodeDiff.llmNodes.toDelete.map((n) => n.backendId!).filter((id) => id != null),
        file_extractor_node_ids: nodeDiff.fileExtractorNodes.toDelete
            .map((n) => n.backendId!)
            .filter((id) => id != null),
        audio_transcription_node_ids: nodeDiff.audioToTextNodes.toDelete
            .map((n) => n.backendId!)
            .filter((id) => id != null),
        end_node_ids: nodeDiff.endNodes.toDelete.map((n) => n.backendId!).filter((id) => id != null),
        subgraph_node_ids: nodeDiff.subgraphNodes.toDelete.map((n) => n.backendId!).filter((id) => id != null),
        webhook_trigger_node_ids: nodeDiff.webhookNodes.toDelete.map((n) => n.backendId!).filter((id) => id != null),
        telegram_trigger_node_ids: nodeDiff.telegramNodes.toDelete.map((n) => n.backendId!).filter((id) => id != null),
        schedule_trigger_node_ids: nodeDiff.scheduleNodes.toDelete.map((n) => n.backendId!).filter((id) => id != null),
        decision_table_node_ids: nodeDiff.decisionTableNodes.toDelete
            .map((n) => n.backendId!)
            .filter((id) => id != null),
        graph_note_ids: nodeDiff.noteNodes.toDelete.map((n) => n.backendId!).filter((id) => id != null),
        code_agent_node_ids: nodeDiff.codeAgentNodes.toDelete.map((n) => n.backendId!).filter((id) => id != null),
        classification_decision_table_node_ids: nodeDiff.classificationDecisionTableNodes.toDelete
            .map((n) => n.backendId!)
            .filter((id) => id != null),
        edge_ids: connectionDiff.toDelete.map((c) => c.data?.id).filter((id): id is number => id != null),
    };

    return {
        save_version: saveVersion,
        start_node_list: nodeItems(nodeDiff.startNodes, (n) => ({
            graph: graphId,
            variables: n.data.initialState ?? {},
            metadata: toNodeMetadata(n),
        })),
        crew_node_list: nodeItems(nodeDiff.crewNodes, (n) => ({
            node_name: n.node_name,
            graph: graphId,
            crew_id: n.data.id,
            input_map: n.input_map || {},
            output_variable_path: n.output_variable_path || null,
            stream_config: n.stream_config ?? {},
            metadata: toNodeMetadata(n),
        })),
        python_node_list: nodeItems(nodeDiff.pythonNodes, (n) => {
            const { use_storage, ...pythonCode } = n.data;
            return {
                node_name: n.node_name,
                graph: graphId,
                python_code: pythonCode,
                input_map: n.input_map || {},
                output_variable_path: n.output_variable_path || null,
                stream_config: n.stream_config ?? {},
                use_storage: use_storage ?? false,
                test_input: n.test_input ?? {},
                metadata: toNodeMetadata(n),
            };
        }),
        llm_node_list: nodeItems(nodeDiff.llmNodes, (n) => ({
            node_name: n.node_name,
            graph: graphId,
            llm_config: n.data.id,
            input_map: n.input_map || {},
            output_variable_path: n.output_variable_path || null,
            metadata: toNodeMetadata(n),
        })),
        file_extractor_node_list: nodeItems(nodeDiff.fileExtractorNodes, (n) => ({
            node_name: n.node_name,
            graph: graphId,
            input_map: n.input_map || {},
            output_variable_path: n.output_variable_path || null,
            metadata: toNodeMetadata(n),
        })),
        audio_transcription_node_list: nodeItems(nodeDiff.audioToTextNodes, (n) => ({
            node_name: n.node_name,
            graph: graphId,
            input_map: n.input_map || {},
            output_variable_path: n.output_variable_path || null,
            metadata: toNodeMetadata(n),
        })),
        end_node_list: nodeItems(nodeDiff.endNodes, (n) => ({
            graph: graphId,
            output_map: n.data.output_map ?? { context: 'variables.context' },
            metadata: toNodeMetadata(n),
        })),
        subgraph_node_list: nodeItems(nodeDiff.subgraphNodes, (n) => ({
            node_name: n.node_name,
            graph: graphId,
            subgraph: n.data.id,
            input_map: n.input_map || {},
            output_variable_path: n.output_variable_path || null,
            metadata: toNodeMetadata(n),
        })),
        webhook_trigger_node_list: nodeItems(nodeDiff.webhookNodes, (n) => ({
            node_name: n.node_name,
            graph: graphId,
            python_code: n.data.python_code,
            input_map: n.input_map || {},
            output_variable_path: n.output_variable_path || null,
            webhook_trigger_path: '',
            webhook_trigger: n.data.webhook_trigger,
            metadata: toNodeMetadata(n),
        })),
        telegram_trigger_node_list: nodeItems(nodeDiff.telegramNodes, (n) => ({
            node_name: n.node_name,
            graph: graphId,
            telegram_bot_api_key: n.data.telegram_bot_api_key,
            webhook_trigger: n.data.webhook_trigger,
            fields: n.data.fields,
            metadata: toNodeMetadata(n),
        })),
        schedule_trigger_node_list: nodeItems(nodeDiff.scheduleNodes, (n) => ({
            node_name: n.node_name,
            graph: graphId,
            is_active: n.data.startDateTime ? n.data.isActive : false,
            metadata: toNodeMetadata(n),
            schedule: n.data.startDateTime ? buildScheduleBlock(n) : null,
        })),
        decision_table_node_list: nodeItems(nodeDiff.decisionTableNodes, (n) =>
            buildDecisionTableNodePayload(n, graphId, current.nodes, idMap)
        ),
        graph_note_list: nodeItems(nodeDiff.noteNodes, (n) => ({
            node_name: n.node_name,
            graph: graphId,
            content: n.data.content,
            metadata: { ...toNodeMetadata(n), backgroundColor: n.data.backgroundColor ?? null },
        })),
        code_agent_node_list: nodeItems(nodeDiff.codeAgentNodes, (n) => ({
            node_name: n.node_name,
            graph: graphId,
            llm_config: n.data?.llm_config_id ?? null,
            agent_mode: n.data?.agent_mode ?? 'code_interpreter',
            session_id: n.data?.session_id ?? '',
            system_prompt: n.data?.system_prompt ?? '',
            stream_handler_code: n.data?.stream_handler_code ?? '',
            libraries: n.data?.libraries ?? [],
            polling_interval_ms: n.data?.polling_interval_ms ?? 100,
            silence_indicator_s: n.data?.silence_indicator_s ?? 3,
            indicator_repeat_s: n.data?.indicator_repeat_s ?? 5,
            chunk_timeout_s: n.data?.chunk_timeout_s ?? 30,
            inactivity_timeout_s: n.data?.inactivity_timeout_s ?? 120,
            max_wait_s: n.data?.max_wait_s ?? 300,
            input_map: n.input_map,
            output_variable_path: n.output_variable_path,
            stream_config: n.stream_config ?? {},
            output_schema: n.data?.output_schema ?? {},
            use_storage: n.data?.use_storage ?? false,
            metadata: toNodeMetadata(n),
        })),
        classification_decision_table_node_list: nodeItems(nodeDiff.classificationDecisionTableNodes, (n) =>
            buildCdtNodePayload(n, graphId, current.nodes, idMap, current.connections)
        ),
        edge_list: [...edgeList, ...edgeUpdateList],
        deleted,
    };
}
