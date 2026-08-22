import { GetProjectRequest } from '../../../features/projects/models/project.model';
import { GetAgentRequest } from '../../../features/staff/models/agent.model';
import { GetTaskRequest } from '../../../features/tasks/models/task.model';

// Base GraphMessage interface
export interface GraphMessage {
    id: number;
    session: number; // This maps to sessionId in TypedGraphMessage
    name: string;
    execution_order: number; // Snake case from API
    created_at: string; // This is the timestamp
    message_data: MessageData; // Snake case from API - This will be one of the specific message types
    uuid?: string;
    metadata: Record<string, unknown>;
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
    GRAPH_END = 'graph_end',
    CONDITION_GROUP = 'condition_group',
    CLASSIFICATION_PROMPT = 'classification_prompt',
    CONDITION_GROUP_MANIPULATION = 'condition_group_manipulation',
    CODE_AGENT_STREAM = 'code_agent_stream',
    FINDINGS = 'findings',
    TASK_NODE_STREAM = 'task_node_stream',
    AGENT_NODE_STREAM = 'agent_node_stream',
}

export type FinishStopReason = 'completed' | 'schema_satisfied' | 'max_iter_reached';

export interface FinishOutputTokenUsage {
    prompt_tokens: number;
    completion_tokens: number;
    total_tokens: number;
}

export interface FinishOutput {
    message?: string;
    stop_reason?: FinishStopReason;
    iterations?: number;
    tool_invocations?: number;
    token_usage?: FinishOutputTokenUsage;
    [key: string]: unknown;
}

export interface FinishMessageData {
    output: FinishOutput;
    state: Record<string, Record<string, unknown>>;
    message_type: MessageType.FINISH;
    additional_data?: Record<string, unknown> | null;
    sse_visible?: boolean;
}

export interface StartMessageData {
    input: Record<string, unknown>;
    message_type: MessageType.START; // Using snake_case from API
}

export interface ErrorMessageData {
    details: string | Record<string, unknown>;
    message_type: MessageType.ERROR; // Using snake_case from API
}

export interface PythonMessageData {
    python_code_execution_data: Record<string, unknown>;
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
    status_data: Record<string, unknown>; // Using snake_case from API
    message_type: MessageType.UPDATE_SESSION_STATUS; // Using snake_case from API
    associatedProject?: GetProjectRequest;
}

export interface ExtractedChunk {
    text: string;
    order: number;
    source: string;
    similarity: number;
}

export interface RagSearchConfig {
    rag_type: string;
    search_limit: number;
    similarity_threshold: number;
}

export interface ExtractedChunksMessageData {
    crew_id: number;
    agent_id: number;
    collection_id: number;
    retrieved_chunks: number;
    knowledge_query: string;
    chunks: ExtractedChunk[];
    message_type: MessageType.EXTRACTED_CHUNKS;
    associatedProject?: GetProjectRequest;
    rag_search_config: RagSearchConfig;
}

// State history item interface for subflow messages
export interface StateHistoryItem {
    name: string;
    type: string;
    input: Record<string, unknown>;
    output: Record<string, unknown>;
    variables: Record<string, unknown>;
    additional_data: Record<string, unknown>;
}

// Subflow state interface
export interface SubflowState {
    variables: Record<string, unknown>;
    state_history: StateHistoryItem[];
}

export interface StartSubflowMessageData {
    input: Record<string, unknown>;
    state: SubflowState;
    subgraph_id: number;
    subgraph_execution_id?: string;
    messages_count_by_subgraph: Record<number, Record<string, number>>;
    message_type: MessageType.SUBGRAPH_START;
}

export interface FinishSubflowMessageData {
    output: Record<string, unknown>;
    state: SubflowState;
    message_type: MessageType.SUBGRAPH_FINISH;
}

export interface GraphEndMessageData {
    end_node_result: Record<string, unknown>;
    message_type: MessageType.GRAPH_END;
}

export interface ConditionGroupMessageData {
    group_name: string;
    result: boolean;
    expression: string | null;
    message_type: MessageType.CONDITION_GROUP;
}

export interface ClassificationPromptMessageData {
    prompt_id: string;
    prompt_text: string;
    raw_response: string;
    parsed_result: unknown;
    result_variable: string;
    usage: Record<string, number>;
    message_type: MessageType.CLASSIFICATION_PROMPT;
}

export interface ConditionGroupManipulationMessageData {
    group_name: string;
    state: Record<string, Record<string, unknown>>;
    changed_variables: Record<string, unknown>;
    message_type: MessageType.CONDITION_GROUP_MANIPULATION;
}

export interface CodeAgentToolCall {
    name: string;
    input: string;
    output: string;
    state: string;
}

export interface CodeAgentStreamMessageData {
    text: string;
    tool_calls?: CodeAgentToolCall[];
    is_final: boolean;
    step_id?: number;
    message_type: MessageType.CODE_AGENT_STREAM;
}

export type FindingSeverity = 'info' | 'low' | 'medium' | 'high' | 'critical';

export interface Finding {
    title: string;
    severity: FindingSeverity;
    category: string | null;
    file: string | null;
    line: number | null;
    detail: string | null;
}

export interface FindingsMessageData {
    title: string | null;
    summary: string | null;
    findings: Finding[];
    total_submitted: number;
    total_returned: number;
    truncated: boolean;
    message: string;
    message_type: MessageType.FINDINGS;
}

// TaskNode / AgentNode stream events (task_start / tool_call / tool_result / task_finish) —
// same envelope shape, only message_type differs. AgentNode events MAY additionally carry
// `data.task` to indicate which sub-task the activity belongs to (absent for single-task
// agents). task_start/task_finish events carry `data.task`, and task_finish additionally
// carries the task's output text in `data.message`.
export interface NodeStreamTaskRef {
    name: string;
    order: number;
}

export interface NodeStreamToolCallData {
    id: string;
    name: string;
    arguments: string;
    truncated?: boolean;
    token_usage?: Record<string, number>;
    task?: NodeStreamTaskRef;
}

export interface NodeStreamToolResultData {
    tool_call_id: string;
    name: string;
    content: string;
    is_error?: boolean;
    truncated?: boolean;
    token_usage?: Record<string, number>;
    task?: NodeStreamTaskRef;
}

export interface NodeStreamTaskStartData {
    task: NodeStreamTaskRef;
}

export interface NodeStreamTaskFinishData {
    task: NodeStreamTaskRef;
    message: string;
    iterations?: number;
    stop_reason?: string;
    token_usage?: Record<string, number>;
    tool_invocations?: number;
    truncated?: boolean;
}

interface NodeStreamMessageDataBase {
    event: 'task_start' | 'tool_call' | 'tool_result' | 'task_finish';
    step_id: number;
    is_final: boolean;
    sse_visible?: boolean;
    data: NodeStreamToolCallData | NodeStreamToolResultData | NodeStreamTaskStartData | NodeStreamTaskFinishData;
}

export interface TaskNodeStreamMessageData extends NodeStreamMessageDataBase {
    message_type: MessageType.TASK_NODE_STREAM;
}

export interface AgentNodeStreamMessageData extends NodeStreamMessageDataBase {
    message_type: MessageType.AGENT_NODE_STREAM;
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
    | FinishSubflowMessageData
    | GraphEndMessageData
    | ConditionGroupMessageData
    | ClassificationPromptMessageData
    | ConditionGroupManipulationMessageData
    | CodeAgentStreamMessageData
    | FindingsMessageData
    | TaskNodeStreamMessageData
    | AgentNodeStreamMessageData;
