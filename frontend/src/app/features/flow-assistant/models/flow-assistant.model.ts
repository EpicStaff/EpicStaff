export interface SessionSummary {
    id: number;
    title: string;
    started_at: string;
    last_message_at: string;
    message_count: number;
}

export interface FlowAssistantConfig {
    id: number;
    llm_config: number | null;
    system_prompt_preview: string;
    updated_at: string;
}

export interface FlowAssistantConversation {
    id: number;
    flow_assistant: number;
    user: number;
    messages: FlowAssistantMessage[];
    started_at: string;
    last_message_at: string;
}

export interface ToolCall {
    id: string;
    name: string;
    arguments: Record<string, unknown>;
}

export interface ActionItem {
    type: 'button' | 'link' | 'prompt';
    action?: 'sendAction' | 'sendButtonTextWithParams' | 'link' | 'openFlow' | 'openNode' | 'refreshCache';
    text: string;
    params?: Record<string, unknown>;
}

export interface EfTableColumn {
    key: string;
    title?: string;
    type?: 'text' | 'number' | 'boolean' | 'date';
    visible?: boolean;
    editable?: boolean;
}

export interface EfTable {
    id?: string;
    rows: Record<string, unknown>[];
    columns?: EfTableColumn[];
    isEditable?: boolean;
    isSortable?: boolean;
    defaultSortField?: string;
    rowsSelectionType?: 'edit' | 'select' | 'multiSelect';
}

export type FlowAssistantMessage =
    | {
          role: 'system' | 'user';
          content: string;
          tool_calls?: ToolCall[];
      }
    | {
          role: 'assistant';
          content: string;
          tool_calls?: ToolCall[];
          ef_tables?: EfTable[];
          action_message?: ActionItem[];
          interrupted?: boolean;
      }
    | { role: 'tool'; content: string; tool_call_id: string; name: string; arguments?: Record<string, unknown> };

export interface StreamTokenEvent {
    type: 'token';
    content: string;
}

export interface StreamToolCallEvent {
    type: 'tool_call';
    id: string;
    name: string;
    arguments: Record<string, unknown>;
    node_name_hint?: string;
    subgraph_name_hint?: string;
}

export interface StreamToolResultEvent {
    type: 'tool_result';
    id: string;
    name: string;
    content: string;
}

export interface StreamDoneEvent {
    type: 'done';
    interrupted?: boolean;
    reasoning_observed?: boolean;
}

export interface StreamStructuredEvent {
    type: 'structured';
    message: string;
    ef_tables: EfTable[];
    action_message: ActionItem[];
}

export type StreamEvent =
    | StreamTokenEvent
    | StreamToolCallEvent
    | StreamToolResultEvent
    | StreamStructuredEvent
    | StreamDoneEvent;

export interface SendMessageResponse {
    stream_url: string;
}
