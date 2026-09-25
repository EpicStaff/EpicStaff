import {
    GraphBasicSearchConfig,
    GraphDriftSearchConfig,
    GraphGlobalSearchConfig,
    GraphLocalSearchConfig,
    GraphSearchMethod,
} from '@shared/models';

import { AgentNode } from '../../../visual-programming/core/models/agent-node.model';
import { GetAudioToTextNodeRequest } from '../../../visual-programming/core/models/audio-to-text.model';
import {
    CDTPythonCodeBlock,
    GetClassificationDecisionTableNodeRequest,
} from '../../../visual-programming/core/models/classification-decision-table-node.model';
import { GetDecisionTableNodeRequest } from '../../../visual-programming/core/models/decision-table-node.model';
import { Edge } from '../../../visual-programming/core/models/edge.model';
import { EndNode } from '../../../visual-programming/core/models/end-node.model';
import { GetFileExtractorNodeRequest } from '../../../visual-programming/core/models/file-extractor.model';
import { GraphNote } from '../../../visual-programming/core/models/graph-note.model';
import { StartNode } from '../../../visual-programming/core/models/start-node.model';
import { SubGraphNode } from '../../../visual-programming/core/models/subgraph-node.model';
import { TaskNode } from '../../../visual-programming/core/models/task-node.model';
import { TelegramTriggerNodeField } from '../../../visual-programming/core/models/telegram-trigger.model';
import { ToolMode } from '../../agent-definitions/models/surface.model';
import { RestoreWarning } from './graph.model';

/**
 * Shape of `GET /graph-versions/{id}/preview/` — the version's stored export snapshot
 * (backend `GraphStrategy.export_entity`, converted to the current import version and
 * filtered of missing dependencies). Node rows come from the per-node import serializers:
 * `graph`, `created_at` and `updated_at` are never present, nested python code has no `id`
 * and carries `libraries` as a space-separated string.
 */

/** Every `node_type` the backend export emits (backend `NODE_RELATIONS`). */
export type SnapshotNodeType =
    | 'StartNode'
    | 'EndNode'
    | 'GraphNote'
    | 'PythonNode'
    | 'TaskNode'
    | 'AgentNode'
    | 'FileExtractorNode'
    | 'AudioTranscriptionNode'
    | 'SubgraphNode'
    | 'WebhookTriggerNode'
    | 'TelegramTriggerNode'
    | 'ScheduleTriggerNode'
    | 'DecisionTableNode'
    | 'ClassificationDecisionTableNode'
    | 'KnowledgeNode';

type ExcludedExportFields = 'graph' | 'created_at' | 'updated_at';

/** A node DTO as the export writes it: without the excluded fields, tagged with its `node_type`. */
type SnapshotNodeOf<TNodeType extends SnapshotNodeType, TNodeDto> = Omit<TNodeDto, ExcludedExportFields> & {
    node_type: TNodeType;
};

interface SnapshotNodeBase<TNodeType extends SnapshotNodeType> {
    id: number;
    node_type: TNodeType;
    node_name: string;
    metadata: Record<string, unknown>;
}

export interface SnapshotPythonCode {
    code: string;
    /** Space-separated library list, e.g. `"requests pandas"`. */
    libraries: string;
    entrypoint: string;
    global_kwargs?: Record<string, unknown>;
}

export type SnapshotStartNode = SnapshotNodeOf<'StartNode', StartNode>;

export type SnapshotEndNode = SnapshotNodeOf<'EndNode', EndNode>;

export type SnapshotGraphNote = SnapshotNodeOf<'GraphNote', GraphNote>;

/** `inline_surface` as the export writes it (backend `serialize_inline_surface`), not the live shape. */
export interface SnapshotInlineSurface {
    instructions: string;
    tools: {
        PythonCodeTool?: { python_tool_id: number | null; mode: ToolMode }[];
        MCPTool?: { mcp_tool_id: number | null; mode: ToolMode }[];
    };
}

export type SnapshotTaskNode = SnapshotNodeOf<'TaskNode', Omit<TaskNode, 'inline_surface'>> & {
    inline_surface: SnapshotInlineSurface | null;
};

export type SnapshotAgentNode = SnapshotNodeOf<'AgentNode', Omit<AgentNode, 'inline_surface'>> & {
    inline_surface: SnapshotInlineSurface | null;
};

export type SnapshotFileExtractorNode = SnapshotNodeOf<'FileExtractorNode', GetFileExtractorNodeRequest>;

export type SnapshotAudioTranscriptionNode = SnapshotNodeOf<'AudioTranscriptionNode', GetAudioToTextNodeRequest>;

export type SnapshotSubgraphNode = SnapshotNodeOf<'SubgraphNode', Omit<SubGraphNode, 'subgraph_detail'>>;

export type SnapshotDecisionTableNode = SnapshotNodeOf<'DecisionTableNode', GetDecisionTableNodeRequest>;

export interface SnapshotPythonNode extends SnapshotNodeBase<'PythonNode'> {
    input_map: Record<string, unknown>;
    output_variable_path: string | null;
    test_input: Record<string, string | number | boolean>;
    use_storage?: boolean;
    python_code: SnapshotPythonCode;
}

export interface SnapshotWebhookTriggerNode extends SnapshotNodeBase<'WebhookTriggerNode'> {
    /** The trigger's id (the live API nests the object); null when the backend nulled it. */
    webhook_trigger: number | null;
    input_map: Record<string, unknown>;
    output_variable_path: string | null;
    python_code: SnapshotPythonCode;
}

export interface SnapshotTelegramTriggerNode extends SnapshotNodeBase<'TelegramTriggerNode'> {
    /** The trigger's id (the live API nests the object); null when the backend nulled it. */
    webhook_trigger: number | null;
    fields: TelegramTriggerNodeField[];
}

export interface SnapshotScheduleTriggerNode extends SnapshotNodeBase<'ScheduleTriggerNode'> {
    is_active: boolean;
    timezone: string;
    run_mode: string | null;
    start_date_time: string | null;
    every: number | null;
    unit: string | null;
    weekdays: string[] | null;
    end_type: string | null;
    end_date_time: string | null;
    max_runs: number | null;
    current_runs: number;
    next_run_date_time: string | null;
}

export type SnapshotClassificationPythonCode = Omit<CDTPythonCodeBlock, 'libraries' | 'secret_ids' | 'secrets'> & {
    /** Space-separated library list, e.g. `"requests pandas"`. */
    libraries: string;
};

export type SnapshotClassificationDecisionTableNode = SnapshotNodeOf<
    'ClassificationDecisionTableNode',
    Omit<GetClassificationDecisionTableNodeRequest, 'pre_python_code' | 'post_python_code'>
> & {
    pre_python_code: SnapshotClassificationPythonCode | null;
    post_python_code: SnapshotClassificationPythonCode | null;
};

export interface SnapshotNaiveSearchConfig {
    search_limit: number | null;
    /** A Django DecimalField, so the export writes it as a string, e.g. `"0.70"`. */
    similarity_threshold: string | null;
    is_suggested?: boolean;
}

export interface SnapshotKnowledgeNode extends SnapshotNodeBase<'KnowledgeNode'> {
    input_map: Record<string, unknown>;
    output_variable_path: string | null;
    source_collection: number | null;
    rag_type: 'naive' | 'graph' | null;
    rag_id: number | null;
    query: string;
    search_method: GraphSearchMethod | null;
    naive_search_config?: SnapshotNaiveSearchConfig | null;
    graph_basic_search_config?: GraphBasicSearchConfig | null;
    graph_local_search_config?: GraphLocalSearchConfig | null;
    graph_global_search_config?: GraphGlobalSearchConfig | null;
    graph_drift_search_config?: GraphDriftSearchConfig | null;
}

/** One exported node row, discriminated on `node_type`. */
export type SnapshotNode =
    | SnapshotStartNode
    | SnapshotEndNode
    | SnapshotGraphNote
    | SnapshotPythonNode
    | SnapshotTaskNode
    | SnapshotAgentNode
    | SnapshotFileExtractorNode
    | SnapshotAudioTranscriptionNode
    | SnapshotSubgraphNode
    | SnapshotWebhookTriggerNode
    | SnapshotTelegramTriggerNode
    | SnapshotScheduleTriggerNode
    | SnapshotDecisionTableNode
    | SnapshotClassificationDecisionTableNode
    | SnapshotKnowledgeNode;

export type SnapshotEdge = Omit<Edge, ExcludedExportFields>;

export interface SnapshotConditionalEdge {
    id: number;
    source_node_id: number;
    python_code: SnapshotPythonCode;
    input_map: Record<string, unknown>;
    metadata: Record<string, unknown>;
}

/** Secret names declared per node, keyed by the snapshot node id, then by the python-code field name. */
export type SnapshotNodeSecretDeclarations = Record<string, Record<string, string[]>>;

export interface SnapshotConditionalEdgeSecretDeclaration {
    source_node_id: number;
    names: string[];
}

export interface SnapshotSecretDeclarations {
    nodes?: SnapshotNodeSecretDeclarations;
    conditional_edges?: SnapshotConditionalEdgeSecretDeclaration[];
    /** Telegram bot API key secret name, keyed by the snapshot node id. */
    telegram?: Record<string, string>;
}

export interface GraphVersionSnapshot {
    nodes: SnapshotNode[];
    edge_list?: SnapshotEdge[];
    conditional_edge_list?: SnapshotConditionalEdge[];
    metadata?: Record<string, unknown>;
    secret_declarations?: SnapshotSecretDeclarations;
}

export interface PreviewGraphVersionResponse {
    snapshot: GraphVersionSnapshot;
    warnings: RestoreWarning[];
}
