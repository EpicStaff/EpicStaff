/**
 * Comparison functions — extract only the fields that should be compared
 * when determining if a node has changed.
 *
 * Each node type has two functions:
 *   - getXxxForComparisonFromBackend — extracts comparable fields from backend model
 *   - getXxxForComparisonFromUI       — extracts comparable fields from UI model
 */

import { GetProjectRequest } from '../../../features/projects/models/project.model';
import {
    CrewNode,
} from '../../../pages/flows-page/components/flow-visual-programming/models/crew-node.model';
import {
    PythonNode,
} from '../../../pages/flows-page/components/flow-visual-programming/models/python-node.model';
import {
    GetLLMNodeRequest,
} from '../../../pages/flows-page/components/flow-visual-programming/models/llm-node.model';
import {
    GetFileExtractorNodeRequest,
} from '../../../pages/flows-page/components/flow-visual-programming/models/file-extractor.model';
import {
    GetAudioToTextNodeRequest,
} from '../../../pages/flows-page/components/flow-visual-programming/models/audio-to-text.model';
import {
    SubGraphNode,
} from '../../../pages/flows-page/components/flow-visual-programming/models/subgraph-node.model';
import {
    GetWebhookTriggerNodeRequest,
} from '../../../pages/flows-page/components/flow-visual-programming/models/webhook-trigger';
import {
    GetTelegramTriggerNodeRequest,
} from '../../../pages/flows-page/components/flow-visual-programming/models/telegram-trigger.model';
import {
    ConditionalEdge,
} from '../../../pages/flows-page/components/flow-visual-programming/models/conditional-edge.model';
import {
    GetDecisionTableNodeRequest,
} from '../../../pages/flows-page/components/flow-visual-programming/models/decision-table-node.model';
import {
    ProjectNodeModel,
    PythonNodeModel,
    LLMNodeModel,
    FileExtractorNodeModel,
    AudioToTextNodeModel,
    SubGraphNodeModel,
    WebhookTriggerNodeModel,
    TelegramTriggerNodeModel,
    EdgeNodeModel,
    NodeModel,
} from '../../core/models/node.model';
import { ResolvedConditionalEdge, NodeUIMetadata, getUIMetadataForComparison } from './save-graph.types';
import { EndNode } from '../../../pages/flows-page/components/flow-visual-programming/models/end-node.model';
import { EndNodeModel } from '../../core/models/node.model';

// ─────────────────────────────────────────────────────────────────────────────
// Shared UI-metadata comparison helpers
// ─────────────────────────────────────────────────────────────────────────────

/**
 * Extracts the metadata object from a backend node for comparison.
 * Falls back to a zeroed-out object so a missing metadata never equals a real one.
 */
function getBackendMetadataForComparison(node: { metadata?: any }): NodeUIMetadata {
    const m = node.metadata ?? {};
    return {
        position: m['position'] ?? { x: 0, y: 0 },
        color: m['color'] ?? '',
        icon: m['icon'] ?? '',
        size: m['size'] ?? { width: 0, height: 0 },
        parentId: m['parentId'] ?? null,
    };
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
        metadata: getBackendMetadataForComparison(node),
    };
}

export function getCrewNodeForComparisonFromUI(node: ProjectNodeModel) {
    return {
        node_name: node.node_name,
        crew_id: (node.data as GetProjectRequest).id,
        input_map: node.input_map || {},
        output_variable_path: node.output_variable_path || null,
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
// ConditionalEdge
// ─────────────────────────────────────────────────────────────────────────────

export function getConditionalEdgeForComparisonFromBackend(node: ConditionalEdge) {
    return {
        source: node.source || null,
        node_name: (node.metadata as any)?.['node_name'] ?? '',
        libraries: node.python_code.libraries,
        code: (node.python_code.code || '').trimEnd(),
        entrypoint: node.python_code.entrypoint,
        input_map: node.input_map,
        then: node.then,
        metadata: getBackendMetadataForComparison(node),
    };
}

export function getConditionalEdgeForComparisonFromUI(node: ResolvedConditionalEdge) {
    return {
        source: node.sourceName || null,
        node_name: node.edgeNode.node_name,
        libraries: node.edgeNode.data.python_code.libraries,
        code: (node.edgeNode.data.python_code.code || '').trimEnd(),
        entrypoint: node.edgeNode.data.python_code.entrypoint,
        input_map: node.edgeNode.input_map || {},
        then: node.targetName,
        metadata: getUIMetadataForComparison(node.edgeNode),
    };
}

// ─────────────────────────────────────────────────────────────────────────────
// DecisionTableNode
// ─────────────────────────────────────────────────────────────────────────────

/**
 * Resolves a node ID (UUID) or already-a-name to a node_name using the UI node list.
 */
function resolveNodeName(idOrName: string | null, allNodes: NodeModel[]): string | null {
    if (!idOrName) return null;
    const match = allNodes.find(n => n.id === idOrName);
    return match ? match.node_name : idOrName;
}

export function getDecisionTableNodeForComparisonFromBackend(node: GetDecisionTableNodeRequest) {
    return {
        node_name: node.node_name,
        condition_groups: node.condition_groups.map(g => ({
            group_name: g.group_name,
            group_type: g.group_type,
            expression: g.expression,
            conditions: g.conditions.map(c => ({
                condition_name: c.condition_name,
                condition: c.condition,
            })),
            manipulation: g.manipulation,
            next_node: g.next_node,
            order: g.order,
        })),
        default_next_node: node.default_next_node,
        next_error_node: node.next_error_node,
        metadata: getBackendMetadataForComparison(node),
    };
}

export function getDecisionTableNodeForComparisonFromUI(
    node: NodeModel,
    allNodes: NodeModel[]
) {
    const tableData = (node as any).data?.table;
    const groups = ((tableData?.condition_groups ?? []) as any[])
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
        node_name: node.node_name,
        condition_groups: groups,
        default_next_node: resolveNodeName(tableData?.default_next_node, allNodes),
        next_error_node: resolveNodeName(tableData?.next_error_node, allNodes),
        metadata: getUIMetadataForComparison(node as any),
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
        output_map: (node.data as any).output_map ?? { context: 'variables.context' },
        metadata: getUIMetadataForComparison(node),
    };
}

// ─────────────────────────────────────────────────────────────────────────────
// NoteNode
// ─────────────────────────────────────────────────────────────────────────────

import { NoteNode } from '../../../pages/flows-page/components/flow-visual-programming/models/note-node.model';
import { NoteNodeModel } from '../../core/models/node.model';

export function getNoteNodeForComparisonFromBackend(node: NoteNode) {
    return {
        node_name: node.node_name,
        content: node.content,
        metadata: getBackendMetadataForComparison(node),
    };
}

export function getNoteNodeForComparisonFromUI(node: NoteNodeModel) {
    return {
        node_name: node.node_name,
        content: node.data.content,
        metadata: {
            ...getUIMetadataForComparison(node),
            backgroundColor: node.data.backgroundColor ?? null,
        },
    };
}

