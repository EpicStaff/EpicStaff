import { GetPythonCodeToolRequest } from '../../features/tools/models/python-code-tool.model';
import { GetMcpToolRequest } from '../../features/tools/models/mcp-tool.model';
import { FullTask } from './full-task.model';
import { GetToolRequest } from '../../features/tools/models/tool.model';
import { ToolUniqueName } from './agent.model';
import { GetToolConfigRequest } from '../../features/tools/models/tool_config.model';

export interface GetTaskRequest {
    id: number;

    name: string;
    instructions: string;
    expected_output: string;
    knowledge_query?: string | null;

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
        data: GetToolConfigRequest | GetPythonCodeToolRequest | GetMcpToolRequest;
    }[];
}

export interface CreateTaskRequest {
    name: string;
    instructions: string;
    expected_output: string;
    knowledge_query?: string | null;

    order?: number | null;
    human_input?: boolean;
    async_execution?: boolean;
    config?: any | null;
    output_model?: any | null;

    crew?: number | null;
    agent?: number | null;
    task_context_list?: number[];
    configured_tools?: number[];
    python_code_tools?: number[];
    mcp_tools?: number[];
    tool_ids?: ToolUniqueName[];
}
export interface UpdateTaskRequest {
    id: number;

    name: string;
    instructions: string;
    expected_output: string;
    knowledge_query?: string | null;

    order?: number | null;
    human_input?: boolean;
    async_execution?: boolean;
    config?: any | null;
    output_model?: any | null;

    crew?: number | null;
    agent?: number | null;
    task_context_list?: number[];
    configured_tools?: number[];
    python_code_tools?: number[];
    mcp_tools?: number[];
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
