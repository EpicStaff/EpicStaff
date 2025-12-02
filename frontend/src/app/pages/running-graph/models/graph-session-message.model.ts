import { Agent, GetAgentRequest } from '../../../shared/models/agent.model';
import { GetProjectRequest } from '../../../features/projects/models/project.model';
import { GetTaskRequest } from '../../../shared/models/task.model';

// Base GraphMessage interface
export interface GraphMessage {
  id: number;
  session: number; // This maps to sessionId in TypedGraphMessage
  name: string;
  execution_order: number; // Snake case from API
  created_at: string; // This is the timestamp
  message_data: MessageData; // Snake case from API - This will be one of the specific message types
  uuid?: string;
}

// Message type constants
export enum MessageType {
  FINISH = 'finish',
  START = 'start',
  ERROR = 'error',
  PYTHON = 'python',
  LLM = 'llm',
  AGENT = 'agent',
  AGENT_FINISH = 'agent_finish',
  USER = 'user',
  TASK = 'task',
  UPDATE_SESSION_STATUS = 'update_session_status',
  EXTRACTED_CHUNKS = 'extracted_chunks',
  SUBGRAPH_START = 'subgraph_start',
  SUBGRAPH_FINISH = 'subgraph_finish',
}

// Message data interfaces - these match the camelCase structure used in your code
export interface FinishMessageData {
  output: any;
  state: Record<string, any>;
  message_type: MessageType.FINISH; 
  additional_data?: Record<string, any>; 
}

export interface StartMessageData {
  input: any;
  message_type: MessageType.START; // Using snake_case from API
}

export interface ErrorMessageData {
  details: any;
  message_type: MessageType.ERROR; // Using snake_case from API
}

export interface PythonMessageData {
  python_code_execution_data: Record<string, any>;
  message_type: MessageType.PYTHON;
}

export interface LLMMessageData {
  response: string;
  message_type: MessageType.LLM; // Using snake_case from API
}

export interface AgentMessageData {
  crew_id: number; // Using snake_case from API
  agent_id: number; // Using snake_case from API
  thought: string;
  tool: string;
  tool_input: string; // Using snake_case from API
  text: string;
  result: string;
  message_type: MessageType.AGENT; // Using snake_case from API
  associatedAgent?: GetAgentRequest;
  associatedProject?: GetProjectRequest;
}

export interface AgentFinishMessageData {
  crew_id: number; // Using snake_case from API
  agent_id: number; // Using snake_case from API
  thought: string;
  text: string;
  output: string;
  message_type: MessageType.AGENT_FINISH; // Using snake_case from API
  associatedAgent?: GetAgentRequest;
  associatedProject?: GetProjectRequest;
}

export interface UserMessageData {
  crew_id: number; // Using snake_case from API
  text: string;
  message_type: MessageType.USER; // Using snake_case from API

  associatedProject?: GetProjectRequest;
}

export interface TaskMessageData {
  crew_id: number; // Using snake_case from API
  task_id: number; // Using snake_case from API
  description: string;
  raw: string;
  name: string;
  expected_output: string; // Using snake_case from API
  agent: string;
  message_type: MessageType.TASK; // Using snake_case from API
  associatedTask?: GetTaskRequest;
  associatedProject?: GetProjectRequest;
}

export interface UpdateSessionStatusMessageData {
  crew_id: number; // Using snake_case from API
  status: string;
  status_data: Record<string, any>; // Using snake_case from API
  message_type: MessageType.UPDATE_SESSION_STATUS; // Using snake_case from API
  associatedProject?: GetProjectRequest;
}

export interface ExtractedChunk {
  chunk_text: string;
  chunk_order: number;
  chunk_source: string;
  chunk_similarity: number;
}

export interface ExtractedChunksMessageData {
  crew_id: number;
  agent_id: number;
  collection_id: number;
  retrieved_chunks: number;
  similarity_threshold: number;
  search_limit: number;
  knowledge_query: string;
  chunks: ExtractedChunk[];
  message_type: MessageType.EXTRACTED_CHUNKS;
  associatedProject?: GetProjectRequest;
}

// State history item interface for subflow messages
export interface StateHistoryItem {
  name: string;
  type: string;
  input: Record<string, any>;
  output: Record<string, any>;
  variables: Record<string, any>;
  additional_data: Record<string, any>;
}

// Subflow state interface
export interface SubflowState {
  variables: Record<string, any>;
  state_history: StateHistoryItem[];
}

export interface StartSubflowMessageData {
  input: Record<string, any>;
  state: SubflowState;
  message_type: MessageType.SUBGRAPH_START;
}

export interface FinishSubflowMessageData {
  output: any;
  state: SubflowState;
  message_type: MessageType.SUBGRAPH_FINISH;
}

// Type union for all message data types
export type MessageData =
  | FinishMessageData
  | StartMessageData
  | ErrorMessageData
  | PythonMessageData
  | LLMMessageData
  | AgentMessageData
  | AgentFinishMessageData
  | UserMessageData
  | TaskMessageData
  | UpdateSessionStatusMessageData
  | ExtractedChunksMessageData
  | StartSubflowMessageData
  | FinishSubflowMessageData;
