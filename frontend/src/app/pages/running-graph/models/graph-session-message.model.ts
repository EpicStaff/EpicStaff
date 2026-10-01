import { KeyValueMode } from '@shared/models';

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
    EXTRACTED_CHUNKS = 'extracted_chunks',
    SUBGRAPH_START = 'subgraph_start',
    SUBGRAPH_FINISH = 'subgraph_finish',
    GRAPH_END = 'graph_end',
    CONDITION_GROUP = 'condition_group',
    CLASSIFICATION_PROMPT = 'classification_prompt',
    CONDITION_GROUP_MANIPULATION = 'condition_group_manipulation',
    FINDINGS = 'findings',
    TASK_NODE_STREAM = 'task_node_stream',
    AGENT_NODE_STREAM = 'agent_node_stream',
    KEY_VALUE = 'key_value',
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

export interface ExtractedChunk {
    text: string;
    order: number;
    source?: string;
    similarity?: number;
}

// A bare string only appears in old saved graph messages from the crew path,
// which put the answer in chunks[0]. New graph messages use `answer` and send `chunks: []`.
export type RawExtractedChunk = ExtractedChunk | string;

export type ExtractedChunksRagType = 'naive' | 'graph';

// Two backend paths emit this with different shapes (EST-3985):
//   - redis-agent/TaskNode (shared/models/knowledge.py): `rag_type`, graph
//     params nested under `search_params.search_method`.
//   - CrewAI/Project-node (shared/models/knowledge_new.py via
//     RagSearchConfigFactory): `rag_strategy`, graph params flat (`method`,
//     `max_context_tokens`).
// Naive's fields are named the same in both.
export interface RagSearchConfig {
    rag_type?: ExtractedChunksRagType;
    rag_strategy?: ExtractedChunksRagType;
    search_limit?: number;
    similarity_threshold?: number;
    method?: string;
    max_context_tokens?: number;
    search_params?: {
        search_method?: string;
        max_context_tokens?: number;
        [key: string]: unknown;
    };
}

export interface ExtractedChunksMessageData {
    /** CrewAI leftover the backend still stamps on knowledge-search payloads. */
    crew_id?: number;
    agent_id: number;
    collection_id: number;
    retrieved_chunks: number;
    knowledge_query: string;
    /** Missing on old saved messages; fall back to `rag_search_config.rag_type` / `rag_strategy`. */
    rag_type?: ExtractedChunksRagType;
    /** naive: the chunks; graph: `[]` (old crew-path messages: the answer string in chunks[0]). */
    chunks: RawExtractedChunk[];
    /** graph: the answer, `""` when the grounding guard found nothing; naive: null. */
    answer?: string | null;
    message_type: MessageType.EXTRACTED_CHUNKS;
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

export interface ClassificationTokenUsage {
    prompt_tokens?: number;
    completion_tokens?: number;
    total_tokens?: number;
    cached_prompt_tokens?: number;
    total_cost_usd?: number;
    [key: string]: number | undefined;
}

export interface ClassificationPromptMessageData {
    prompt_id: string;
    prompt_text: string;
    raw_response: string;
    parsed_result: unknown;
    result_variable: string;
    usage: ClassificationTokenUsage;
    message_type: MessageType.CLASSIFICATION_PROMPT;
}

export interface ConditionGroupManipulationMessageData {
    group_name: string;
    state: Record<string, Record<string, unknown>>;
    changed_variables: Record<string, unknown>;
    message_type: MessageType.CONDITION_GROUP_MANIPULATION;
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

export type KeyValueMessageMode = KeyValueMode;

// read: `path` is the target variable and `found` is set.
// write: `path` is the source path (may carry a `|default` suffix) and `created` is set.
// delete: `path` is null and `found` tells whether the key was stored (and so deleted); `deleted_count` on the
// message is the number of keys actually removed. Delete messages from before deletes reported it carry
// `found: null` and `value: null` (crew has always sent both fields, null by default).
// `value` is the full JSON value: the stored one for a found read, the one written for a write, the deleted one for
// a found delete, and null when not found. When the message hit its size budget, `truncated` is true and `value`
// is a string holding the first 200 chars of the JSON text.
export interface KeyValueMessageEntry {
    key: string;
    path: string | null;
    // read and delete; null for a write, and for a delete message from before deletes reported it.
    found: boolean | null;
    created: boolean | null;
    value: unknown;
    truncated: boolean;
}

export interface KeyValueMessageData {
    mode: KeyValueMessageMode;
    table_id: number;
    table_name: string;
    entries: KeyValueMessageEntry[];
    deleted_count: number | null;
    message_type: MessageType.KEY_VALUE;
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
    | ExtractedChunksMessageData
    | StartSubflowMessageData
    | FinishSubflowMessageData
    | GraphEndMessageData
    | ConditionGroupMessageData
    | ClassificationPromptMessageData
    | ConditionGroupManipulationMessageData
    | FindingsMessageData
    | TaskNodeStreamMessageData
    | AgentNodeStreamMessageData
    | KeyValueMessageData;
