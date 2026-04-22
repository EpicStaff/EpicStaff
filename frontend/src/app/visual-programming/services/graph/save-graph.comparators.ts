/**
 * Comparison functions — extract only the fields that should be compared
 * when determining if a node has changed.
 *
 * Each node type has two functions:
 *   - getXxxForComparisonFromBackend — extracts comparable fields from backend model
 *   - getXxxForComparisonFromUI       — extracts comparable fields from UI model
 */

import { GetProjectRequest } from '../../../features/projects/models/project.model';
import { GetAudioToTextNodeRequest } from '../../../pages/flows-page/components/flow-visual-programming/models/audio-to-text.model';
import { GetClassificationDecisionTableNodeRequest } from '../../../pages/flows-page/components/flow-visual-programming/models/classification-decision-table-node.model';
import { GetCodeAgentNodeRequest } from '../../../pages/flows-page/components/flow-visual-programming/models/code-agent-node.model';
import { ConditionalEdge } from '../../../pages/flows-page/components/flow-visual-programming/models/conditional-edge.model';
import { CrewNode } from '../../../pages/flows-page/components/flow-visual-programming/models/crew-node.model';
import { GetDecisionTableNodeRequest } from '../../../pages/flows-page/components/flow-visual-programming/models/decision-table-node.model';
import { EndNode } from '../../../pages/flows-page/components/flow-visual-programming/models/end-node.model';
import { GetFileExtractorNodeRequest } from '../../../pages/flows-page/components/flow-visual-programming/models/file-extractor.model';
import { GetLLMNodeRequest } from '../../../pages/flows-page/components/flow-visual-programming/models/llm-node.model';
import { PythonNode } from '../../../pages/flows-page/components/flow-visual-programming/models/python-node.model';
import { SubGraphNode } from '../../../pages/flows-page/components/flow-visual-programming/models/subgraph-node.model';
import { GetTelegramTriggerNodeRequest } from '../../../pages/flows-page/components/flow-visual-programming/models/telegram-trigger.model';
import { GetWebhookTriggerNodeRequest } from '../../../pages/flows-page/components/flow-visual-programming/models/webhook-trigger';
import { PromptConfig } from '../../core/models/classification-decision-table.model';
import { ConditionGroup } from '../../core/models/decision-table.model';
import {
    AudioToTextNodeModel,
    ClassificationDecisionTableNodeModel,
    CodeAgentNodeModel,
    DecisionTableNodeModel,
    FileExtractorNodeModel,
    LLMNodeModel,
    NodeModel,
    ProjectNodeModel,
    PythonNodeModel,
    SubGraphNodeModel,
    TelegramTriggerNodeModel,
    WebhookTriggerNodeModel,
} from '../../core/models/node.model';
import { EndNodeModel } from '../../core/models/node.model';
import { getUIMetadataForComparison, NodeUIMetadata, ResolvedConditionalEdge } from './save-graph.types';

// ─────────────────────────────────────────────────────────────────────────────
// Shared UI-metadata comparison helpers
// ─────────────────────────────────────────────────────────────────────────────

function getBackendMetadataForComparison(node: { metadata?: unknown }): NodeUIMetadata {
    const m = node.metadata && typeof node.metadata === 'object' ? (node.metadata as Record<string, unknown>) : {};

    const position = m['position'] as { x?: number; y?: number } | undefined;
    const size = m['size'] as { width?: number; height?: number } | undefined;

    return {
        position: { x: position?.x ?? 0, y: position?.y ?? 0 },
        color: typeof m['color'] === 'string' ? m['color'] : '',
        icon: typeof m['icon'] === 'string' ? m['icon'] : '',
        size: {
            width: size?.width ?? 0,
            height: size?.height ?? 0,
        },
        nodeNumber: typeof m['nodeNumber'] === 'number' ? m['nodeNumber'] : undefined,
    };
}

/** Resolves a frontend UUID to a backend ID using the node list. */
function resolveBackendId(uuid: string | null, allNodes: NodeModel[]): number | null {
    if (!uuid) return null;
    const match = allNodes.find((n) => n.id === uuid);
    return match?.backendId ?? null;
}

// ─────────────────────────────────────────────────────────────────────────────
// CrewNode (ProjectNodeModel)
// ─────────────────────────────────────────────────────────────────────────────

export function getCrewNodeForComparisonFromBackend(node: CrewNode) {
    return {
        node_name: node.node_name,
        crew_id: node.crew.id,
        input_map: node.input_map,
        output_variable_path: node.output_variable_path,
        stream_config: node.stream_config ?? {},
        metadata: getBackendMetadataForComparison(node),
    };
}

export function getCrewNodeForComparisonFromUI(node: ProjectNodeModel) {
    return {
        node_name: node.node_name,
        crew_id: (node.data as GetProjectRequest).id,
        input_map: node.input_map || {},
        output_variable_path: node.output_variable_path || null,
        stream_config: node.stream_config ?? {},
        metadata: getUIMetadataForComparison(node),
    };
}

// ─────────────────────────────────────────────────────────────────────────────
// PythonNode
// ─────────────────────────────────────────────────────────────────────────────

export function getPythonNodeForComparisonFromBackend(node: PythonNode) {
    return {
        node_name: node.node_name,
        libraries: node.python_code.libraries,
        code: (node.python_code.code || '').trimEnd(),
        entrypoint: node.python_code.entrypoint,
        input_map: node.input_map,
        output_variable_path: node.output_variable_path,
        stream_config: node.stream_config ?? {},
        use_storage: node.use_storage ?? false,
        metadata: getBackendMetadataForComparison(node),
    };
}

export function getPythonNodeForComparisonFromUI(node: PythonNodeModel) {
    return {
        node_name: node.node_name,
        libraries: node.data.libraries,
        code: (node.data.code || '').trimEnd(),
        entrypoint: node.data.entrypoint,
        input_map: node.input_map || {},
        output_variable_path: node.output_variable_path || null,
        stream_config: node.stream_config ?? {},
        use_storage: node.data.use_storage ?? false,
        metadata: getUIMetadataForComparison(node),
    };
}

// ─────────────────────────────────────────────────────────────────────────────
// LLMNode
// ─────────────────────────────────────────────────────────────────────────────

export function getLLMNodeForComparisonFromBackend(node: GetLLMNodeRequest) {
    return {
        node_name: node.node_name,
        llm_config: node.llm_config,
        input_map: node.input_map,
        output_variable_path: node.output_variable_path,
        metadata: getBackendMetadataForComparison(node),
    };
}

export function getLLMNodeForComparisonFromUI(node: LLMNodeModel) {
    return {
        node_name: node.node_name,
        llm_config: node.data.id,
        input_map: node.input_map || {},
        output_variable_path: node.output_variable_path || null,
        metadata: getUIMetadataForComparison(node),
    };
}

// ─────────────────────────────────────────────────────────────────────────────
// FileExtractorNode
// ─────────────────────────────────────────────────────────────────────────────

export function getFileExtractorNodeForComparisonFromBackend(node: GetFileExtractorNodeRequest) {
    return {
        node_name: node.node_name,
        input_map: node.input_map,
        output_variable_path: node.output_variable_path,
        metadata: getBackendMetadataForComparison(node),
    };
}

export function getFileExtractorNodeForComparisonFromUI(node: FileExtractorNodeModel) {
    return {
        node_name: node.node_name,
        input_map: node.input_map || {},
        output_variable_path: node.output_variable_path || null,
        metadata: getUIMetadataForComparison(node),
    };
}

// ─────────────────────────────────────────────────────────────────────────────
// AudioToTextNode
// ─────────────────────────────────────────────────────────────────────────────

export function getAudioToTextNodeForComparisonFromBackend(node: GetAudioToTextNodeRequest) {
    return {
        node_name: node.node_name,
        input_map: node.input_map,
        output_variable_path: node.output_variable_path,
        metadata: getBackendMetadataForComparison(node),
    };
}

export function getAudioToTextNodeForComparisonFromUI(node: AudioToTextNodeModel) {
    return {
        node_name: node.node_name,
        input_map: node.input_map || {},
        output_variable_path: node.output_variable_path || null,
        metadata: getUIMetadataForComparison(node),
    };
}

// ─────────────────────────────────────────────────────────────────────────────
// SubGraphNode
// ─────────────────────────────────────────────────────────────────────────────

export function getSubGraphNodeForComparisonFromBackend(node: SubGraphNode) {
    return {
        node_name: node.node_name,
        subgraph: node.subgraph,
        input_map: node.input_map,
        output_variable_path: node.output_variable_path,
        metadata: getBackendMetadataForComparison(node),
    };
}

export function getSubGraphNodeForComparisonFromUI(node: SubGraphNodeModel) {
    return {
        node_name: node.node_name,
        subgraph: node.data.id,
        input_map: node.input_map || {},
        output_variable_path: node.output_variable_path || null,
        metadata: getUIMetadataForComparison(node),
    };
}

// ─────────────────────────────────────────────────────────────────────────────
// WebhookTriggerNode
// ─────────────────────────────────────────────────────────────────────────────

export function getWebhookTriggerNodeForComparisonFromBackend(node: GetWebhookTriggerNodeRequest) {
    return {
        node_name: node.node_name,
        libraries: node.python_code.libraries,
        code: (node.python_code.code || '').trimEnd(),
        entrypoint: node.python_code.entrypoint,
        input_map: node.input_map,
        output_variable_path: node.output_variable_path,
        webhook_trigger: node.webhook_trigger,
        metadata: getBackendMetadataForComparison(node),
    };
}

export function getWebhookTriggerNodeForComparisonFromUI(node: WebhookTriggerNodeModel) {
    return {
        node_name: node.node_name,
        libraries: node.data.python_code.libraries,
        code: (node.data.python_code.code || '').trimEnd(),
        entrypoint: node.data.python_code.entrypoint,
        input_map: node.input_map || {},
        output_variable_path: node.output_variable_path || null,
        webhook_trigger: node.data.webhook_trigger,
        metadata: getUIMetadataForComparison(node),
    };
}

// ─────────────────────────────────────────────────────────────────────────────
// TelegramTriggerNode
// ─────────────────────────────────────────────────────────────────────────────

export function getTelegramTriggerNodeForComparisonFromBackend(node: GetTelegramTriggerNodeRequest) {
    return {
        node_name: node.node_name,
        telegram_bot_api_key: node.telegram_bot_api_key,
        fields: node.fields,
        metadata: getBackendMetadataForComparison(node),
    };
}

export function getTelegramTriggerNodeForComparisonFromUI(node: TelegramTriggerNodeModel) {
    return {
        node_name: node.node_name,
        telegram_bot_api_key: node.data.telegram_bot_api_key,
        fields: node.data.fields,
        metadata: getUIMetadataForComparison(node),
    };
}

// ─────────────────────────────────────────────────────────────────────────────
// ConditionalEdge (now uses source_node_id and stores then_node_id in metadata)
// ─────────────────────────────────────────────────────────────────────────────

export function getConditionalEdgeForComparisonFromBackend(node: ConditionalEdge) {
    const thenRaw =
        node.metadata && typeof node.metadata === 'object'
            ? (node.metadata as Record<string, unknown>)['then_node_id']
            : undefined;
    const then_node_id = typeof thenRaw === 'number' ? thenRaw : null;

    return {
        source_node_id: node.source_node_id,
        libraries: node.python_code.libraries,
        code: (node.python_code.code || '').trimEnd(),
        entrypoint: node.python_code.entrypoint,
        input_map: node.input_map,
        then_node_id,
        metadata: getBackendMetadataForComparison(node),
    };
}

export function getConditionalEdgeForComparisonFromUI(node: ResolvedConditionalEdge) {
    return {
        source_node_id: node.sourceBackendId,
        libraries: node.edgeNode.data.python_code.libraries,
        code: (node.edgeNode.data.python_code.code || '').trimEnd(),
        entrypoint: node.edgeNode.data.python_code.entrypoint,
        input_map: node.edgeNode.input_map || {},
        then_node_id: node.targetBackendId,
        metadata: getUIMetadataForComparison(node.edgeNode),
    };
}

// ─────────────────────────────────────────────────────────────────────────────
// DecisionTableNode (now uses _node_id fields instead of node name strings)
// ─────────────────────────────────────────────────────────────────────────────

export function getDecisionTableNodeForComparisonFromBackend(node: GetDecisionTableNodeRequest) {
    return {
        node_name: node.node_name,
        condition_groups: node.condition_groups.map((g) => ({
            group_name: g.group_name,
            group_type: g.group_type,
            expression: g.expression,
            conditions: g.conditions.map((c) => ({
                condition_name: c.condition_name,
                condition: c.condition,
            })),
            manipulation: g.manipulation,
            next_node_id: g.next_node_id,
            order: g.order,
        })),
        default_next_node_id: node.default_next_node_id,
        next_error_node_id: node.next_error_node_id,
        metadata: getBackendMetadataForComparison(node),
    };
}

export function getDecisionTableNodeForComparisonFromUI(node: NodeModel, allNodes: NodeModel[]) {
    const tableData = (node as DecisionTableNodeModel).data.table;
    const groups = tableData.condition_groups
        .filter((g) => g.valid !== false)
        .sort((a, b) => (a.order ?? Number.MAX_SAFE_INTEGER) - (b.order ?? Number.MAX_SAFE_INTEGER))
        .map((g, idx) => ({
            group_name: g.group_name,
            group_type: g.group_type,
            expression: g.expression,
            conditions: g.conditions.map((c) => ({
                condition_name: c.condition_name,
                condition: c.condition,
            })),
            manipulation: g.manipulation,
            next_node_id: resolveBackendId(g.next_node, allNodes),
            order: typeof g.order === 'number' ? g.order : idx + 1,
        }));

    return {
        node_name: node.node_name,
        condition_groups: groups,
        default_next_node_id: resolveBackendId(tableData.default_next_node, allNodes),
        next_error_node_id: resolveBackendId(tableData.next_error_node, allNodes),
        metadata: getUIMetadataForComparison(node),
    };
}

// ─────────────────────────────────────────────────────────────────────────────
// EndNode
// ─────────────────────────────────────────────────────────────────────────────

export function getEndNodeForComparisonFromBackend(node: EndNode) {
    return {
        node_name: node.node_name,
        output_map: node.output_map,
        metadata: getBackendMetadataForComparison(node),
    };
}

export function getEndNodeForComparisonFromUI(node: EndNodeModel) {
    return {
        node_name: node.node_name,
        output_map: node.data.output_map ?? { context: 'variables.context' },
        metadata: getUIMetadataForComparison(node),
    };
}

// ─────────────────────────────────────────────────────────────────────────────
// GraphNote
// ─────────────────────────────────────────────────────────────────────────────

import { GraphNote } from '../../../pages/flows-page/components/flow-visual-programming/models/graph-note.model';
import { GraphNoteModel } from '../../core/models/node.model';

export function getGraphNoteForComparisonFromBackend(node: GraphNote) {
    return {
        node_name: node.node_name,
        content: node.content,
        metadata: getBackendMetadataForComparison(node),
    };
}

export function getGraphNoteForComparisonFromUI(node: GraphNoteModel) {
    return {
        node_name: node.node_name,
        content: node.data.content,
        metadata: {
            ...getUIMetadataForComparison(node),
            backgroundColor: node.data.backgroundColor ?? null,
        },
    };
}

// ─────────────────────────────────────────────────────────────────────────────
// CodeAgentNode
// ─────────────────────────────────────────────────────────────────────────────

export function getCodeAgentNodeForComparisonFromBackend(node: GetCodeAgentNodeRequest) {
    return {
        node_name: node.node_name,
        llm_config: node.llm_config,
        agent_mode: node.agent_mode,
        session_id: node.session_id,
        system_prompt: node.system_prompt,
        stream_handler_code: node.stream_handler_code,
        libraries: node.libraries,
        polling_interval_ms: node.polling_interval_ms,
        silence_indicator_s: node.silence_indicator_s,
        indicator_repeat_s: node.indicator_repeat_s,
        chunk_timeout_s: node.chunk_timeout_s,
        inactivity_timeout_s: node.inactivity_timeout_s,
        max_wait_s: node.max_wait_s,
        input_map: node.input_map,
        output_variable_path: node.output_variable_path,
        stream_config: node.stream_config ?? {},
        output_schema: node.output_schema ?? {},
        use_storage: node.use_storage ?? false,
        metadata: getBackendMetadataForComparison(node),
    };
}

export function getCodeAgentNodeForComparisonFromUI(node: CodeAgentNodeModel) {
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
        metadata: getUIMetadataForComparison(node),
    };
}

// ─────────────────────────────────────────────────────────────────────────────
// ClassificationDecisionTableNode
// ─────────────────────────────────────────────────────────────────────────────

export function getClassificationDecisionTableNodeForComparisonFromBackend(
    node: GetClassificationDecisionTableNodeRequest
) {
    return {
        node_name: node.node_name,
        pre_computation_code: node.pre_python_code?.code || null,
        condition_groups: node.condition_groups.map((g) => ({
            group_name: g.group_name,
            order: g.order,
            expression: g.expression,
            prompt_id: g.prompt_id,
            manipulation: g.manipulation,
            continue_flag: g.continue_flag,
            next_node_id: g.next_node_id,
            // route_code: g.route_code,  // TEMP: testing without route_code
            dock_visible: g.dock_visible,
            field_expressions: g.field_expressions,
            field_manipulations: g.field_manipulations,
        })),
        prompt_configs: [...(node.prompt_configs ?? [])]
            .sort((a, b) => a.prompt_key.localeCompare(b.prompt_key))
            .map((p) => ({
                prompt_key: p.prompt_key,
                prompt_text: p.prompt_text ?? '',
                llm_config: p.llm_config ?? null,
                output_schema: p.output_schema ?? null,
                result_variable: p.result_variable ?? '',
                variable_mappings: p.variable_mappings ?? {},
            })),
        default_llm_config: node.default_llm_config ?? null,
        default_next_node: node.default_next_node,
        next_error_node: node.next_error_node,
        pre_input_map: node.pre_input_map || {},
        pre_output_variable_path: node.pre_output_variable_path || null,
        post_computation_code: node.post_python_code?.code || null,
        post_input_map: node.post_input_map || {},
        post_output_variable_path: node.post_output_variable_path || null,
        pre_libraries: node.pre_python_code?.libraries || [],
        post_libraries: node.post_python_code?.libraries || [],
    };
}

export function getClassificationDecisionTableNodeForComparisonFromUI(
    node: ClassificationDecisionTableNodeModel,
    allNodes: NodeModel[] = []
) {
    const tableData = node.data?.table;
    const preCode = tableData?.pre_computation?.code || tableData?.pre_computation_code || null;
    const groups = (tableData?.condition_groups || [])
        .sort(
            (a: ConditionGroup & { continue_flag?: boolean }, b: ConditionGroup & { continue_flag?: boolean }) =>
                (a.order ?? Number.MAX_SAFE_INTEGER) - (b.order ?? Number.MAX_SAFE_INTEGER)
        )
        .map((g: ConditionGroup & { continue_flag?: boolean }, idx: number) => ({
            group_name: g.group_name,
            order: typeof g.order === 'number' ? g.order : idx + 1,
            expression: g.expression || null,
            prompt_id: g.prompt_id || null,
            manipulation: g.manipulation || null,
            continue_flag: !!(g.continue_flag ?? g.continue),
            next_node_id: resolveBackendId(g.next_node, allNodes),
            // route_code: g.route_code || null,  // TEMP: testing without route_code
            dock_visible: g.dock_visible !== false,
            field_expressions: g.field_expressions || {},
            field_manipulations: g.field_manipulations || {},
        }));

    return {
        node_name: node.node_name,
        pre_computation_code: preCode,
        condition_groups: groups,
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
        post_computation_code: tableData?.post_computation?.code || tableData?.post_computation_code || null,
        post_input_map: tableData?.post_computation?.input_map || tableData?.post_input_map || {},
        post_output_variable_path:
            tableData?.post_computation?.output_variable_path || tableData?.post_output_variable_path || null,
        pre_libraries: tableData?.pre_computation?.libraries || [],
        post_libraries: tableData?.post_computation?.libraries || [],
    };
}
