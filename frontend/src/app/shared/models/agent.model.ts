import { GetPythonCodeToolRequest } from '../../features/tools/models/python-code-tool.model';
import { GetToolRequest } from '../../features/tools/models/tool.model';
import { GetToolConfigRequest } from '../../features/tools/models/tool_config.model';

export type ToolUniqueName =
  | `configured-tool:${number}`
  | `python-code-tool:${number}`;

export interface Agent {
  id: number;

  role: string;
  goal: string;
  backstory: string;

  configured_tools: number[];
  python_code_tools: number[];

  llm_config: number | null;
  fcm_llm_config: number | null;

  allow_delegation: boolean;
  memory: boolean;

  max_iter: number;
  max_rpm: number | null;
  max_execution_time: number | null;
  cache: boolean | null;
  allow_code_execution: boolean | null;
  max_retry_limit: number | null;
  respect_context_window: boolean | null;
  default_temperature: number | null;

  knowledge_collection: number | null;

  realtime_agent: RealtimeAgentConfig;
  tools: {
    unique_name: ToolUniqueName;
    data: GetToolRequest | GetPythonCodeToolRequest;
  }[];
}

export interface RealtimeAgentConfig {
  distance_threshold: string;
  search_limit: number;
  wake_word: string | null;
  stop_prompt: string | null;
  language: string | null;
  voice_recognition_prompt: string | null;
  voice: string;
  realtime_config: number | null;
  realtime_transcription_config: number | null;
}
export interface GetAgentRequest {
  id: number;

  role: string;
  goal: string;
  backstory: string;

  configured_tools: number[];
  python_code_tools: number[];

  llm_config: number | null;
  fcm_llm_config: number | null;

  allow_delegation: boolean;
  memory: boolean;

  max_iter: number;
  max_rpm: number | null;
  max_execution_time: number | null;
  cache: boolean | null;
  allow_code_execution: boolean | null;
  max_retry_limit: number | null;
  respect_context_window: boolean | null;
  default_temperature: number | null;

  knowledge_collection: number | null;
  realtime_agent: RealtimeAgentConfig;
  tools: {
    unique_name: ToolUniqueName;
    data: GetToolConfigRequest | GetPythonCodeToolRequest;
  }[];
}

// Create Agent Request
export interface CreateAgentRequest {
  role: string;
  goal: string;
  backstory: string;

  configured_tools?: number[];
  python_code_tools?: number[];

  llm_config?: number | null;
  fcm_llm_config?: number | null;

  allow_delegation?: boolean;
  memory?: boolean;

  max_iter?: number;
  max_rpm?: number | null;
  max_execution_time?: number | null;
  cache?: boolean | null;
  allow_code_execution?: boolean | null;
  max_retry_limit?: number | null;
  respect_context_window?: boolean | null;
  default_temperature?: number | null;

  knowledge_collection?: number | null;
  realtime_agent?: RealtimeAgentConfig;
  tool_ids: ToolUniqueName[];
}

// Update Agent Request
export interface UpdateAgentRequest {
  id: number;
  role: string;
  goal: string;
  backstory: string;

  configured_tools: number[];
  python_code_tools: number[];

  llm_config: number | null;
  fcm_llm_config: number | null;

  allow_delegation: boolean;
  memory: boolean;

  max_iter: number;
  max_rpm: number | null;
  max_execution_time: number | null;
  cache: boolean | null;
  allow_code_execution: boolean | null;
  max_retry_limit: number | null;
  respect_context_window: boolean | null;
  default_temperature: number | null;

  knowledge_collection: number | null;

  realtime_agent: RealtimeAgentConfig;
  tool_ids: ToolUniqueName[];
}

export type AgentTableItem = Omit<Agent, 'id'> & {
  id: number | null;
};

export interface AgentNode {
  id: number;
  type: 'agent' | 'task';
  reference_id: number;
}
