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
    name: string;
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
  | NoteNodeModel;
