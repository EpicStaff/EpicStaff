export type ChatChannel = 'widget' | 'telegram';
export type ChatConcurrencyPolicy = 'interrupt' | 'queue';
export type ChatBudgetExhaustedBehaviour = 'handoff' | 'reply';
export type ChatConversationMode = 'bot' | 'awaiting_human' | 'human' | 'closed';
export type ChatMessageRole = 'user' | 'assistant' | 'operator' | 'system';
export type ChatInboundAction =
    | 'started'
    | 'interrupted_and_restarted'
    | 'queued'
    | 'forwarded_to_operator'
    | 'budget_exhausted';

// `chat-bindings/`: flow X is exposed as a chat.
export interface ChatBinding {
    id: number;
    graph: number;
    graph_name: string;
    name: string;
    channel: ChatChannel;
    is_active: boolean;
    concurrency_policy: ChatConcurrencyPolicy;
    history_window: number;
    // null = unlimited.
    token_budget_per_conversation: number | null;
    on_budget_exhausted: ChatBudgetExhaustedBehaviour;
    budget_exhausted_message: string;
    handoff_enabled: boolean;
}

export type ChatBindingRequest = Omit<ChatBinding, 'id' | 'graph_name'>;

// `chat-conversations/` (read-only).
export interface ChatConversation {
    id: number;
    binding: number;
    binding_name: string;
    graph: number;
    channel: ChatChannel;
    external_id: string;
    mode: ChatConversationMode;
    assigned_operator: number | null;
    assigned_operator_name: string | null;
    active_session: number | null;
    active_session_status: string | null;
    tokens_used: number;
    token_budget: number | null;
    handoff_reason: string | null;
    last_message_at: string | null;
    last_message_preview: string | null;
}

export interface ChatMessage {
    id: number;
    role: ChatMessageRole;
    content: string;
    session: number | null;
    interrupted: boolean;
    author_name: string | null;
    created_at: string;
}

export interface ChatInboundRequest {
    external_id: string;
    content: string;
}

export interface ChatInboundResponse {
    conversation_id: number;
    message_id: number;
    action: ChatInboundAction;
}
