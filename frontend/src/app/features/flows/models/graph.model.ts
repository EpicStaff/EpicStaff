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
}

// Author and last-edit fields are optional like created_at/updated_at: light graphs are also
// built client-side from SubflowLightDto (flow-card, flows-menu), which carries no authorship.
export interface GetGraphLightRequest extends Partial<AuthorshipFields> {
    id: number;
    uuid: string;
    name: string;
    description: string;
    tags?: string[];
    epicchat_enabled?: boolean;
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
    Pick<GraphDto, 'name' | 'description' | 'tags' | 'label_ids' | 'epicchat_enabled' | 'save_version'>
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

export interface RestoreWarning {
    type: 'node_skipped' | 'edge_dropped' | string;
    node_name?: string;
    node_type?: string;
    node_id?: number;
    missing_node_id?: number;
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
