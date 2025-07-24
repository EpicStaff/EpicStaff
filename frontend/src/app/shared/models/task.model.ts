import { GetPythonCodeToolRequest } from '../../features/tools/models/python-code-tool.model';
import { FullTask } from './full-task.model';
import { GetToolRequest } from '../../features/tools/models/tool.model';
import { ToolUniqueName } from './agent.model';
import { GetToolConfigRequest } from '../../features/tools/models/tool_config.model';

export interface GetTaskRequest {
  id: number;

  name: string;
  instructions: string;
  expected_output: string;

  order: number | null;
  human_input: boolean;
  async_execution: boolean;
  config: any | null;
  output_model: any | null;

  crew: number | null;
  agent: number | null;

  task_context_list: number[];

  tools: {
    unique_name: ToolUniqueName;
    data: GetToolConfigRequest | GetPythonCodeToolRequest;
  }[];
}

export interface CreateTaskRequest {
  name: string;
  instructions: string;
  expected_output: string;

  order?: number | null;
  human_input?: boolean;
  async_execution?: boolean;
  config?: any | null;
  output_model?: any | null;

  crew?: number | null;
  agent?: number | null;
  task_context_list?: number[];
  tool_ids?: ToolUniqueName[];
}
export interface UpdateTaskRequest {
  id: number;

  name: string;
  instructions: string;
  expected_output: string;

  order?: number | null;
  human_input?: boolean;
  async_execution?: boolean;
  config?: any | null;
  output_model?: any | null;

  crew?: number | null;
  agent?: number | null;
  task_context_list?: number[];

  tool_ids?: ToolUniqueName[];
}
export interface TableFullTask extends Omit<FullTask, 'id'> {
  id: number | string;
}

//deprecated
export type TaskTableItem = Omit<GetTaskRequest, 'id'> & {
  id: number | null;
  assignedAgentRole: string;
};
