import { AgentNode } from '../../../visual-programming/core/models/agent-node.model';
import { GetAudioToTextNodeRequest } from '../../../visual-programming/core/models/audio-to-text.model';
import { GetClassificationDecisionTableNodeRequest } from '../../../visual-programming/core/models/classification-decision-table-node.model';
import { ConditionalEdge } from '../../../visual-programming/core/models/conditional-edge.model';
import { GetDecisionTableNodeRequest } from '../../../visual-programming/core/models/decision-table-node.model';
import { Edge } from '../../../visual-programming/core/models/edge.model';
import { EndNode } from '../../../visual-programming/core/models/end-node.model';
import { GetFileExtractorNodeRequest } from '../../../visual-programming/core/models/file-extractor.model';
import { FlowModel } from '../../../visual-programming/core/models/flow.model';
import { GraphNote } from '../../../visual-programming/core/models/graph-note.model';
import { GetKnowledgeRetrieverNodeRequest } from '../../../visual-programming/core/models/knowledge-retriever-node.model';
import { GetLLMNodeRequest } from '../../../visual-programming/core/models/llm-node.model';
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

export interface GetGraphLightRequest {
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

export interface GraphDto extends GetGraphLightRequest {
    save_version: number;
    start_node_list: StartNode[];
    python_node_list: PythonNode[];
    task_node_list: TaskNode[];
    agent_node_list?: AgentNode[];
    edge_list: Edge[];
    conditional_edge_list: ConditionalEdge[];
    llm_node_list: GetLLMNodeRequest[];
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
}

export interface CreateGraphDtoRequest {
    name: string;

    description?: string;
    metadata?: Record<string, unknown>;
    tags?: string[];
    start_node_list?: StartNode[];
    python_node_list?: PythonNode[];
    edge_list?: Edge[];
    conditional_edge_list?: ConditionalEdge[];
    llm_node_list?: GetLLMNodeRequest[];
    file_extractor_node_list?: GetFileExtractorNodeRequest[];
    webhook_trigger_node_list?: GetWebhookTriggerNodeRequest[];
    telegram_trigger_node_list?: GetTelegramTriggerNodeRequest[];
    end_node_list?: EndNode[];
    subgraph_node_list?: SubGraphNode[];
    decision_table_node_list?: GetDecisionTableNodeRequest[];
    schedule_trigger_node_list?: CreateScheduleTriggerNodeRequest[];
    knowledge_node_list?: GetKnowledgeRetrieverNodeRequest[];
}

export interface UpdateGraphDtoRequest {
    id: number;
    name: string;

    description: string;
    metadata: FlowModel | Record<string, unknown>;
    tags?: string[];
    save_version?: number;
}

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
