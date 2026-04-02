import { GetGraphLightRequest } from '../../../features/flows/models/graph.model';
import { GetProjectRequest } from '../../../features/projects/models/project.model';
import { GetLlmConfigRequest } from '../../../features/settings-dialog/models/llms/LLM_config.model';
import { GetAgentRequest } from '../../../features/staff/models/agent.model';
import { CreateTaskRequest } from '../../../features/tasks/models/task.model';
import { CustomPythonCode } from '../../../features/tools/models/python-code.model';
import { ToolConfig } from '../../../features/tools/models/tool-config.model';
import { CodeAgentNodeData } from '../../../pages/flows-page/components/flow-visual-programming/models/code-agent-node.model';
import { CustomConditionalEdgeModelForNode } from '../../../pages/flows-page/components/flow-visual-programming/models/conditional-edge.model';
import { TelegramTriggerNodeField } from '../../../pages/flows-page/components/flow-visual-programming/models/telegram-trigger.model';
import { NodeType } from '../enums/node-type';
import { DecisionTableNode } from './decision-table.model';
import { ViewPort } from './port.model';
import { WebhookTriggerModel } from './webhook-trigger.model';

export interface BaseNodeModel {
    id: string;
    /** Backend primary key — set on load, null for newly created nodes. */
    backendId: number | null;
    category: 'web' | 'vscode';
    position: { x: number; y: number };
    ports: ViewPort[] | null;
    node_name: string;
    color: string;
    icon: string;
    size: {
        width: number;
        height: number;
    };
    // UI-only flag for invalid references (e.g. deleted subgraph)
    isBlocked?: boolean;
    // New fields
    input_map: Record<string, unknown>;
    output_variable_path: string | null;
}
export interface StartNodeData {
    initialState: Record<string, unknown>;
}

export interface StartNodeModel extends BaseNodeModel {
    type: NodeType.START;
    data: StartNodeData;
}
export interface PythonNodeModel extends BaseNodeModel {
    type: NodeType.PYTHON;
    data: CustomPythonCode;
    stream_config?: Record<string, boolean>;
}

export interface ProjectNodeModel extends BaseNodeModel {
    type: NodeType.PROJECT;
    data: GetProjectRequest;
    stream_config?: Record<string, boolean>;
}
export interface TaskNodeModel extends BaseNodeModel {
    type: NodeType.TASK;
    data: CreateTaskRequest;
}

export interface AgentNodeModel extends BaseNodeModel {
    type: NodeType.AGENT;
    data: GetAgentRequest;
}
export interface ToolNodeModel extends BaseNodeModel {
    type: NodeType.TOOL;
    data: ToolConfig;
}
export interface LLMNodeModel extends BaseNodeModel {
    type: NodeType.LLM;
    data: GetLlmConfigRequest;
}

export interface EdgeNodeModel extends BaseNodeModel {
    type: NodeType.EDGE;
    data: CustomConditionalEdgeModelForNode;
}

export interface DecisionTableNodeModel extends BaseNodeModel {
    type: NodeType.TABLE;
    data: {
        name: string; // this was used somehere  for saving dec table
        table: DecisionTableNode;
    };
}

export interface GraphNoteModel extends BaseNodeModel {
    type: NodeType.NOTE;
    data: {
        content: string;
        backgroundColor?: string;
    };
}

export interface FileExtractorNodeModel extends BaseNodeModel {
    type: NodeType.FILE_EXTRACTOR;
    data: unknown;
}

export interface AudioToTextNodeModel extends BaseNodeModel {
    type: NodeType.AUDIO_TO_TEXT;
    data: unknown;
}

export interface WebhookTriggerNodeModel extends BaseNodeModel {
    type: NodeType.WEBHOOK_TRIGGER;
    data: {
        webhook_trigger: WebhookTriggerModel | null;
        python_code: CustomPythonCode;
    };
}

export interface TelegramTriggerNodeModel extends BaseNodeModel {
    type: NodeType.TELEGRAM_TRIGGER;
    data: {
        telegram_bot_api_key: string;
        webhook_trigger: WebhookTriggerModel | null;
        fields: TelegramTriggerNodeField[];
    };
}

export interface EndNodeData {
    output_map: Record<string, unknown>;
}

export interface EndNodeModel extends BaseNodeModel {
    type: NodeType.END;
    data: EndNodeData;
}

export interface SubGraphNodeModel extends BaseNodeModel {
    type: NodeType.SUBGRAPH;
    data: GetGraphLightRequest;
}

export interface CodeAgentNodeModel extends BaseNodeModel {
    type: NodeType.CODE_AGENT;
    data: CodeAgentNodeData;
    stream_config?: Record<string, boolean>;
}

export type NodeModel =
    | AgentNodeModel
    | TaskNodeModel
    | ToolNodeModel
    | LLMNodeModel
    | ProjectNodeModel
    | PythonNodeModel
    | EdgeNodeModel
    | StartNodeModel
    | DecisionTableNodeModel
    | GraphNoteModel
    | FileExtractorNodeModel
    | AudioToTextNodeModel
    | SubGraphNodeModel
    | WebhookTriggerNodeModel
    | TelegramTriggerNodeModel
    | EndNodeModel
    | CodeAgentNodeModel;
