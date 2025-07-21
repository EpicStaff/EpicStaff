import { Tool } from '../../features/tools/models/tool.model';

export interface Session {
  id: number;
  status: string;
  created_at: string;
  finished_at: string;
  crew_schema: CrewSchema;
  crew: number;
}

export interface CrewSchema {
  id: number;
  name: string;
  tasks: TaskSchema[];
  agents: AgentSchema[];
  memory: boolean;
  process: 'sequential' | 'hierarchical';
  embedder: EmbedderConfig;
  assignment: string;
  description: string;
  manager_llm: LLMConfig;
}

export interface TaskSchema {
  id: number;
  crew: CrewSchema;
  name: string;
  agent: AgentSchema;
  order: number;
  instructions: string;
  expected_output: string;
}

export interface AgentSchema {
  llm: LLM;
  goal: string;
  role: string;
  tools: Tool[];
  memory: boolean;
  embedder: any;
  max_iter: number;
  backstory: string;
  allow_delegation: boolean;
  function_calling_llm: LLM;
}

export interface LLM {
  config: LLMConfig;
  provider: string;
}

export interface LLMConfig {
  model: string;
  top_p?: number;
  api_key?: string;
  timeout?: number;
  base_url?: string;
  logprobs?: number;
  logit_bias?: any;
  max_tokens?: number;
  api_version?: string;
  temperature: number;
  top_logprobs?: any;
  response_format?: string;
  presence_penalty?: number;
  frequency_penalty?: number;
  max_completion_tokens?: number;
}

export interface EmbedderConfig {
  model: string;
  api_key?: string;
  base_url?: string;
  deployment_name?: string;
}
