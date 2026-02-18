import { CustomConditionalEdgeModelForNode } from '../../../pages/flows-page/components/flow-visual-programming/models/conditional-edge.model';
import { GetAgentRequest } from '../../../shared/models/agent.model';
import { GetLlmConfigRequest } from '../../../features/settings-dialog/models/llms/LLM_config.model';
import { GetProjectRequest } from '../../../features/projects/models/project.model';
import { CreateTaskRequest } from '../../../shared/models/task.model';
import { ToolConfig } from '../../../features/tools/models/tool_config.model';
import { GetPythonCodeToolRequest } from '../../../features/tools/models/python-code-tool.model';
import {
    CreatePythonCodeRequest,
    CustomPythonCode,
} from '../../../features/tools/models/python-code.model';
import { NodeType } from '../enums/node-type';
import { ConnectionModel } from './connection.model';
import { ViewPort } from './port.model';
import { GroupNodeModel } from './group.model';
import { DecisionTableNode } from './decision-table.model';
import {
    TelegramTriggerNodeField
} from "../../../pages/flows-page/components/flow-visual-programming/models/telegram-trigger.model";
import { GetGraphLightRequest } from '../../../features/flows/models/graph.model';

export interface BaseNodeModel {
    id: string;
    category: 'web' | 'vscode';
    position: { x: number; y: number };
    ports: ViewPort[] | null;
    parentId: string | null;
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
    input_map: Record<string, any>;
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
}

export interface ProjectNodeModel extends BaseNodeModel {
    type: NodeType.PROJECT;
    data: GetProjectRequest;
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

export interface NoteNodeModel extends BaseNodeModel {
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
        webhook_trigger_path: string;
        python_code: CustomPythonCode;
    }
}

export interface TelegramTriggerNodeModel extends BaseNodeModel {
    type: NodeType.TELEGRAM_TRIGGER;
    data: {
        telegram_bot_api_key: string;
        fields: TelegramTriggerNodeField[];
    }
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

export type NodeModel =
    | AgentNodeModel
    | TaskNodeModel
    | ToolNodeModel
    | LLMNodeModel
    | ProjectNodeModel
    | PythonNodeModel
    | EdgeNodeModel
    | StartNodeModel
    | GroupNodeModel
    | DecisionTableNodeModel
    | NoteNodeModel
    | FileExtractorNodeModel
    | AudioToTextNodeModel
    | SubGraphNodeModel
    | WebhookTriggerNodeModel
    | TelegramTriggerNodeModel
    | EndNodeModel;
