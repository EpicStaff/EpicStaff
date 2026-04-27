import { GetAudioToTextNodeRequest } from '../../../pages/flows-page/components/flow-visual-programming/models/audio-to-text.model';
import { GetCodeAgentNodeRequest } from '../../../pages/flows-page/components/flow-visual-programming/models/code-agent-node.model';
import { ConditionalEdge } from '../../../pages/flows-page/components/flow-visual-programming/models/conditional-edge.model';
import { CrewNode } from '../../../pages/flows-page/components/flow-visual-programming/models/crew-node.model';
import { GetDecisionTableNodeRequest } from '../../../pages/flows-page/components/flow-visual-programming/models/decision-table-node.model';
import { Edge } from '../../../pages/flows-page/components/flow-visual-programming/models/edge.model';
import { EndNode } from '../../../pages/flows-page/components/flow-visual-programming/models/end-node.model';
import { GetFileExtractorNodeRequest } from '../../../pages/flows-page/components/flow-visual-programming/models/file-extractor.model';
import { GraphNote } from '../../../pages/flows-page/components/flow-visual-programming/models/graph-note.model';
import { GetLLMNodeRequest } from '../../../pages/flows-page/components/flow-visual-programming/models/llm-node.model';
import { PythonNode } from '../../../pages/flows-page/components/flow-visual-programming/models/python-node.model';
import { StartNode } from '../../../pages/flows-page/components/flow-visual-programming/models/start-node.model';
import { SubGraphNode } from '../../../pages/flows-page/components/flow-visual-programming/models/subgraph-node.model';
import { GetTelegramTriggerNodeRequest } from '../../../pages/flows-page/components/flow-visual-programming/models/telegram-trigger.model';
import { GetWebhookTriggerNodeRequest } from '../../../pages/flows-page/components/flow-visual-programming/models/webhook-trigger';
import { FlowModel } from '../../../visual-programming/core/models/flow.model';

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
}

export interface GraphDto extends GetGraphLightRequest {
    start_node_list: StartNode[];
    crew_node_list: CrewNode[];
    python_node_list: PythonNode[];
    edge_list: Edge[];
    conditional_edge_list: ConditionalEdge[];
    llm_node_list: GetLLMNodeRequest[];
    file_extractor_node_list: GetFileExtractorNodeRequest[];
    webhook_trigger_node_list: GetWebhookTriggerNodeRequest[];
    telegram_trigger_node_list: GetTelegramTriggerNodeRequest[];
    end_node_list: EndNode[];
    subgraph_node_list: SubGraphNode[];
    decision_table_node_list: GetDecisionTableNodeRequest[];
    metadata: FlowModel;
    audio_transcription_node_list: GetAudioToTextNodeRequest[];
    graph_note_list: GraphNote[];
    code_agent_node_list: GetCodeAgentNodeRequest[];
}

export interface CreateGraphDtoRequest {
    name: string;

    description?: string;
    metadata?: Record<string, unknown>;
    tags?: string[];
    start_node_list?: StartNode[];
    crew_node_list?: CrewNode[];
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
}

export interface UpdateGraphDtoRequest {
    id: number;
    name: string;

    description: string;
    metadata: FlowModel | Record<string, unknown>;
    tags?: string[];
}

export interface GraphVersionCreateRequest {
    graph_id: number;
    name: string;
    description?: string;
}

export interface GraphVersionDto {
    id: number;
    graph: number;
    name: string;
    description: string;
    dependencies: Record<string, unknown>;
    created_at: string;
}
