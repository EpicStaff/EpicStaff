export type ChatMode = 'bot' | 'awaiting_human' | 'human';
export type ChatRunState = 'idle' | 'processing';
export type ChatMessageRole = 'user' | 'assistant' | 'operator' | 'system';
export type ChatIdentityMode = 'anonymous' | 'signed';
export type ChatBudgetExhaustedBehaviour = 'reply' | 'handoff';
export type ChatSendState = 'processing' | 'forwarded_to_operator' | 'budget_exhausted';
// `section` of `GET /conversations`; never share a row. Waiting: a visitor waits for a person. In progress: an
// operator holds it and answered last. Bot: the bot still runs it. Test: operators' test conversations.
export type ChatInboxSection = 'waiting' | 'in_progress' | 'bot' | 'test';
// `order` of `GET /conversations`: newest or oldest activity first. Waiting ignores it (longest wait first).
export type ChatInboxOrder = 'newest' | 'oldest';

export const CHAT_MODE_LABELS: Record<ChatMode, string> = {
    bot: 'Bot',
    awaiting_human: 'Awaiting human',
    human: 'Human',
};

// `GET /chat/operator/v1/bindings`; `identity_secret` only on create and on a PATCH that switches to `signed`.
export interface ChatBinding {
    id: string;
    org_id: number;
    graph_id: number;
    name: string;
    // Shown to visitors in the widget: the assistant's and the operator's messages are labelled with them.
    bot_display_name: string;
    operator_display_name: string;
    public_key: string;
    allowed_origins: string[];
    identity_mode: ChatIdentityMode;
    is_active: boolean;
    history_window: number;
    max_message_length: number;
    max_turns: number;
    token_budget_per_conversation: number;
    daily_token_budget: number;
    messages_per_minute: number;
    on_budget_exhausted: ChatBudgetExhaustedBehaviour;
    budget_exhausted_message: string;
    handoff_enabled: boolean;
    broken_reason: string | null;
    contract_errors: string[];
    created_at: string;
    updated_at: string;
}

export interface ChatBindingWithSecret extends ChatBinding {
    identity_secret: string | null;
}

export type ChatBindingInput = Pick<
    ChatBinding,
    | 'name'
    | 'bot_display_name'
    | 'operator_display_name'
    | 'graph_id'
    | 'allowed_origins'
    | 'identity_mode'
    | 'history_window'
    | 'max_message_length'
    | 'max_turns'
    | 'messages_per_minute'
    | 'on_budget_exhausted'
    | 'budget_exhausted_message'
    | 'handoff_enabled'
    | 'token_budget_per_conversation'
    | 'daily_token_budget'
>;

// PATCH body: only the keys that changed; the server applies `exclude_unset`.
export type ChatBindingPatch = Partial<ChatBindingInput>;

type ChatBindingBudgets = Pick<ChatBinding, 'token_budget_per_conversation' | 'daily_token_budget'>;

// `GET /bindings/limits`: the server's create defaults and the caps a binding may not exceed.
export interface ChatBindingLimits {
    defaults: ChatBindingBudgets;
    caps: ChatBindingBudgets;
}

export const CHAT_BINDING_DEFAULTS: Omit<
    ChatBindingInput,
    'name' | 'bot_display_name' | 'graph_id' | 'token_budget_per_conversation' | 'daily_token_budget'
> = {
    operator_display_name: 'Support',
    allowed_origins: [],
    identity_mode: 'anonymous',
    history_window: 20,
    max_message_length: 4000,
    max_turns: 200,
    messages_per_minute: 10,
    on_budget_exhausted: 'reply',
    budget_exhausted_message: 'This conversation has reached its limit.',
    handoff_enabled: true,
};

// Both display names; the server refuses longer ones.
export const CHAT_DISPLAY_NAME_MAX = 64;

// `GET /bindings/contract?graph_id=`: what keeps a flow from serving chat; empty when it can.
export interface ChatContractCheck {
    contract_errors: string[];
}

export interface ChatSnippet {
    public_key: string;
    chat_base_url: string;
    snippet: string;
}

// `conversation` is the new row: the stream announces it before this response, while it is not yet selected.
export interface ChatTestConversation {
    visitor_token: string;
    conversation: ChatConversation;
}

// One row of `GET /conversations` and the payload of the inbox `conversation.updated` event.
export interface ChatConversation {
    id: string;
    binding_id: string;
    // Per desk, from 1 in creation order (test conversations included): "Visitor 12".
    visitor_number: number;
    // The verified customer id on a signed desk; null for anonymous and test conversations.
    chat_user_id: string | null;
    mode: ChatMode;
    state: ChatRunState;
    is_test: boolean;
    assigned_operator_id: number | null;
    // The holder's EpicStaff display name; null when nobody holds it or the name is not known yet.
    assigned_operator_name: string | null;
    // Lifetime totals; the `_today` pair is what the per-conversation budget and max_turns count (per UTC day).
    tokens_used: number;
    turns: number;
    tokens_today: number;
    turns_today: number;
    last_message_at: string | null;
    last_message_preview: string;
    // Who wrote the last message; null before the first one.
    last_message_role: ChatMessageRole | null;
    // The operator who wrote it, and their display name (null when not known yet); null unless an operator reply.
    last_message_author_user_id: number | null;
    last_message_author_name: string | null;
    handoff_reason: string;
    // When the conversation left bot mode; null while the bot runs it. The human section's FIFO key.
    handoff_at: string | null;
    // Since when the visitor has waited for a person: set by a hand-off or by a visitor message after the last
    // operator reply; cleared by an operator reply or a return to the bot (a take over keeps it).
    visitor_waiting_since: string | null;
}

// One conversation the Waiting count includes (`GET /inbox/badges`): its desk and holder, to count per desk and Mine.
export interface ChatInboxBadge {
    id: string;
    binding_id: string;
    assigned_operator_id: number | null;
}

// `GET /inbox/badges`: every conversation waiting for a person, org-wide; tests never wait. In progress has no count:
// nothing closes an answered conversation, so that set would only grow.
export interface ChatInboxBadges {
    waiting: ChatInboxBadge[];
}

// Cursor page of `GET /conversations`; `next_cursor` is opaque and null on the last page.
export interface ChatConversationPage {
    results: ChatConversation[];
    next_cursor: string | null;
}

export interface ChatOperatorMessage {
    id: string;
    role: ChatMessageRole;
    content: string;
    actions: unknown[] | null;
    // The widget's action reply on a user message (empty content for an action-only reply); null otherwise.
    action: Record<string, unknown> | null;
    session_id: number | null;
    created_at: string;
    author_user_id: number | null;
    // The authoring operator's display name; null when not known yet and on visitor, bot and system messages.
    author_name: string | null;
}

// Inbox `message.created`: the public message shape plus the conversation it belongs to and, unlike the visitor's
// stream, the operator who wrote it. No `session_id`.
export interface ChatInboxMessageEvent {
    conversation_id: string;
    id: string;
    role: ChatMessageRole;
    content: string;
    actions: unknown[] | null;
    action: Record<string, unknown> | null;
    created_at: string;
    author_user_id: number | null;
    author_name: string | null;
}

// What a visitor message may carry besides its text (public send body); unset keys are not sent.
export interface ChatVisitorMessageExtras {
    action?: Record<string, unknown>;
    chat_extra_data?: Record<string, unknown>;
}

export interface ChatSendResult {
    message_id: string;
    state: ChatSendState;
}

export interface ChatTicket {
    ticket: string;
    expires_in: number;
}

// Every chat service error body; `retry_after` on 429, `contract_errors` on 400 `contract_failed` (resume),
// `field` and `max` on 400 `budget_above_cap`.
export interface ChatErrorBody {
    code: string;
    message: string;
    retry_after?: number;
    contract_errors?: string[];
    field?: string;
    max?: number;
    // On 400 `validation_error`: what was refused, one entry per problem.
    errors?: { message: string }[];
}
