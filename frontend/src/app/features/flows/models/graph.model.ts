import { CreatePythonCodeRequest } from '../../tools/models/python-code.model';
import { FlowModel } from '../../../visual-programming/core/models/flow.model';
import {
    ConditionalEdge,
    CreateConditionalEdgeRequest,
} from '../../../pages/flows-page/components/flow-visual-programming/models/conditional-edge.model';
import {
    CreateCrewNodeRequest,
    CrewNode,
} from '../../../pages/flows-page/components/flow-visual-programming/models/crew-node.model';
import {
    CreateEdgeRequest,
    Edge,
} from '../../../pages/flows-page/components/flow-visual-programming/models/edge.model';
import { GetLLMNodeRequest } from '../../../pages/flows-page/components/flow-visual-programming/models/llm-node.model';
import {
    CreatePythonNodeRequest,
    PythonNode,
} from '../../../pages/flows-page/components/flow-visual-programming/models/python-node.model';
import { StartNode } from '../../../pages/flows-page/components/flow-visual-programming/models/start-node.model';
import { GetFileExtractorNodeRequest } from '../../../pages/flows-page/components/flow-visual-programming/models/file-extractor.model';
import { EndNode } from '../../../pages/flows-page/components/flow-visual-programming/models/end-node.model';
import { SubGraphNode } from '../../../pages/flows-page/components/flow-visual-programming/models/subgraph-node.model';
import { GetAudioToTextNodeRequest } from '../../../pages/flows-page/components/flow-visual-programming/models/audio-to-text.model';
import { GetDecisionTableNodeRequest } from '../../../pages/flows-page/components/flow-visual-programming/models/decision-table-node.model';
import { GetWebhookTriggerNodeRequest } from '../../../pages/flows-page/components/flow-visual-programming/models/webhook-trigger';
import {
    GetTelegramTriggerNodeRequest
} from "../../../pages/flows-page/components/flow-visual-programming/models/telegram-trigger.model";

export interface GraphDto {
    id: number;
    name: string;
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
    description: string;
    metadata: FlowModel;
    tags?: [];
    audio_transcription_node_list: GetAudioToTextNodeRequest[];
}

export interface GetGraphLightRequest {
    id: number;
    name: string;
    description: string;
    tags: string[];
}

export interface CreateGraphDtoRequest {
    name: string;

    description?: string;
    metadata?: any;
    tags?: [];
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
    metadata: any;
    tags?: [];
}
