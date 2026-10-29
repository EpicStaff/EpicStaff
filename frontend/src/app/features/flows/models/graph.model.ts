import { AuthorshipFields, UserSummary } from '@shared/models';

import { AgentNode } from '../../../visual-programming/core/models/agent-node.model';
import { GetAudioToTextNodeRequest } from '../../../visual-programming/core/models/audio-to-text.model';
import { GetClassificationDecisionTableNodeRequest } from '../../../visual-programming/core/models/classification-decision-table-node.model';
import { GetDecisionTableNodeRequest } from '../../../visual-programming/core/models/decision-table-node.model';
import { Edge } from '../../../visual-programming/core/models/edge.model';
import { EndNode } from '../../../visual-programming/core/models/end-node.model';
import { GetFileExtractorNodeRequest } from '../../../visual-programming/core/models/file-extractor.model';
import { FlowModel } from '../../../visual-programming/core/models/flow.model';
import { GraphNote } from '../../../visual-programming/core/models/graph-note.model';
import { GetKeyValueNodeRequest } from '../../../visual-programming/core/models/key-value-node.model';
import { GetKnowledgeRetrieverNodeRequest } from '../../../visual-programming/core/models/knowledge-retriever-node.model';
import { PythonNode } from '../../../visual-programming/core/models/python-node.model';
import {
    CreateScheduleTriggerNodeRequest,
    GetScheduleTriggerNodeRequest,
} from '../../../visual-programming/core/models/schedule-trigger.model';
import { StartNode } from '../../../visual-programming/core/models/start-node.model';
import { SubGraphNode } from '../../../visual-programming/core/models/subgraph-node.model';
import { TaskNode } from '../../../visual-programming/core/models/task-node.model';
import { GetTelegramTriggerNodeRequest } from '../../../visual-programming/core/models/telegram-trigger.model';
import { GetWebhookTriggerNodeRequest } from '../../../visual-programming/core/models/webhook-trigger';

export interface SubflowLightDto {
    id: number;
    name: string;
    description: string;
    tags?: string[];
    label_ids?: number[];
    created_at?: string;
    updated_at?: string;
    save_version?: number;
}

// Author and last-edit fields are optional like created_at/updated_at: light graphs are also
// built client-side from SubflowLightDto (flow-card, flows-menu), which carries no authorship.
export interface GetGraphLightRequest extends Partial<AuthorshipFields> {
    id: number;
    uuid: string;
    name: string;
    description: string;
    tags?: string[];
    label_ids?: number[];
    created_at?: string;
    updated_at?: string;
    subflows?: SubflowLightDto[];
    save_version?: number;
}

// Every graph the API returns (`GraphSerializer`; also `GraphLightSerializer` for copy and graph-light)
// carries the author, the last edit and a non-null `created_at`. The version preview also builds one
// client-side (`mapSnapshotToGraphDto`): it has no authorship (null) and is never persisted, so its
// `created_at` is a placeholder like its `id` and `uuid`.
export interface GraphDto extends GetGraphLightRequest {
    created_by: UserSummary | null;
    created_at: string;
    last_edited_by: UserSummary | null;
    last_edited_at: string | null;
    save_version: number;
    /**
     * Read-only: the highest node number the graph has issued. Never lowered, so a deleted node's
     * number is not given out again (only rebuilding the whole graph content restarts it).
     */
    node_number_seq: number;
    start_node_list: StartNode[];
    python_node_list: PythonNode[];
    task_node_list: TaskNode[];
    agent_node_list?: AgentNode[];
    edge_list: Edge[];
    file_extractor_node_list: GetFileExtractorNodeRequest[];
    webhook_trigger_node_list: GetWebhookTriggerNodeRequest[];
    telegram_trigger_node_list: GetTelegramTriggerNodeRequest[];
    end_node_list: EndNode[];
    subgraph_node_list: SubGraphNode[];
    decision_table_node_list: GetDecisionTableNodeRequest[];
    classification_decision_table_node_list: GetClassificationDecisionTableNodeRequest[];
    metadata: FlowModel;
    audio_transcription_node_list: GetAudioToTextNodeRequest[];
    graph_note_list: GraphNote[];
    schedule_trigger_node_list: GetScheduleTriggerNodeRequest[];
    knowledge_node_list: GetKnowledgeRetrieverNodeRequest[];
    key_value_node_list: GetKeyValueNodeRequest[];
}

/** A graph's nodes and edges, in the shape `GET graphs/{id}/` returns them. */
export type GraphContentDto = Pick<GraphDto, Extract<keyof GraphDto, `${string}_list`>>;

/**
 * `POST graphs/{id}/partial-import/`: the file's nodes and edges, NOT written to the graph. Every id in
 * `content` (nodes, edges, nested rows) belongs to a row that was never committed, so all of it is new;
 * only the dependency refs (LLM configs, agent definitions, webhook triggers...) are real.
 */
export interface PartialImportResponse {
    content: GraphContentDto;
    summary: Record<string, unknown>;
}

export interface CreateGraphDtoRequest {
    name: string;

    description?: string;
    metadata?: Record<string, unknown>;
    tags?: string[];
    start_node_list?: StartNode[];
    python_node_list?: PythonNode[];
    edge_list?: Edge[];
    file_extractor_node_list?: GetFileExtractorNodeRequest[];
    webhook_trigger_node_list?: GetWebhookTriggerNodeRequest[];
    telegram_trigger_node_list?: GetTelegramTriggerNodeRequest[];
    end_node_list?: EndNode[];
    subgraph_node_list?: SubGraphNode[];
    decision_table_node_list?: GetDecisionTableNodeRequest[];
    schedule_trigger_node_list?: CreateScheduleTriggerNodeRequest[];
    knowledge_node_list?: GetKnowledgeRetrieverNodeRequest[];
    key_value_node_list?: GetKeyValueNodeRequest[];
}

export interface UpdateGraphDtoRequest {
    id: number;
    name: string;

    description: string;
    metadata: FlowModel | Record<string, unknown>;
    tags?: string[];
    save_version?: number;
}

// Body of `PATCH /graphs/{id}/`: only the writable graph metadata the app patches. The read-only
// author, timestamps and last edit of a loaded graph are never sent back.
export type PatchGraphDtoRequest = Partial<
    Pick<GraphDto, 'name' | 'description' | 'tags' | 'label_ids' | 'save_version'>
>;

export interface GraphVersionCreateRequest {
    graph_id: number;
    name: string;
    description?: string;
}

export interface GraphVersionDto {
    id: number;
    graph_id: number;
    name: string;
    description: string;
    created_at: string;
}

export interface GraphVersionUpdateRequest {
    name: string;
    description: string;
}

/**
 * Node-anchored warning types (all carry `node_id`) and the keys each adds:
 * - `fk_nulled`: `field` (the nulled foreign key) and `missing_id`;
 * - `decision_table_ref_cleared`: `field` (the route) and `missing_node_id`;
 * - `surface_dropped`, `inline_tool_dropped`: `missing_id`;
 * - `secret_declaration_dropped`: `field` (`python_code`, `pre_python_code`, `post_python_code` or
 *   `telegram_bot_api_key_secret`) and `missing_name`;
 * - `secret_in_recycle_bin`: `field` (as above); the secret is linked, but it is in the recycle bin.
 * - `venv_ref_cleared`: `field` (`python_code`, `pre_python_code` or `post_python_code`) and `missing_id` (the
 *   venv); the venv is not available in this organization, so a restore leaves that code without one.
 *
 * The version preview adds `key_value_table_unbound` entries itself (`field`, `missing_name`): a Key-Value
 * table the version named that no usable table has now. The backend re-binds tables without a warning.
 */
export interface RestoreWarning {
    type:
        | 'node_skipped'
        | 'edge_dropped'
        | 'secret_declaration_dropped'
        | 'secret_in_recycle_bin'
        | 'key_value_table_unbound'
        | 'venv_ref_cleared'
        | string;
    node_name?: string;
    node_type?: string;
    /**
     * The node the warning is about: its snapshot id in a preview response; its new node id (or absent)
     * in a restore response. Absent for graph-level warnings.
     */
    node_id?: number;
    /**
     * The node field the warning is about, e.g. `agent_definition` (`fk_nulled`), `default_next_node_id`
     * (`decision_table_ref_cleared`), or the code field / Telegram bot key field that declared the secret
     * (`python_code`, `telegram_bot_api_key_secret`; `secret_declaration_dropped`, `secret_in_recycle_bin`).
     */
    field?: string;
    /** Id of the missing entity (agent, trigger, subflow, surface, tool, venv). */
    missing_id?: number;
    /** Id of the missing node a decision-table route pointed at (`decision_table_ref_cleared`). */
    missing_node_id?: number;
    /** Name of the missing secret (`secret_declaration_dropped`) or table (`key_value_table_unbound`). */
    missing_name?: string;
    reason: string;
}

export interface GraphRestoreResponse {
    restored: boolean;
    graph_id: number;
    warnings: RestoreWarning[];
    auto_backup_version_id?: number;
    node_id_map?: Record<string, number>;
}

export interface CreateGraphFromVersionResponse {
    created: boolean;
    graph_id: number;
    warnings: RestoreWarning[];
}
