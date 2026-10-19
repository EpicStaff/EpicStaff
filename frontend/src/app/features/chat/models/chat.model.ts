export type ChatMode = 'bot' | 'awaiting_human' | 'human';
export type ChatRunState = 'idle' | 'processing';
export type ChatMessageRole = 'user' | 'assistant' | 'operator' | 'system';
export type ChatIdentityMode = 'anonymous' | 'signed';
export type ChatBudgetExhaustedBehaviour = 'reply' | 'handoff';
export type ChatSendState = 'processing' | 'forwarded_to_operator' | 'budget_exhausted';
// Whether anyone is still on a conversation, whatever its mode. A closed one is read-only and never reopens: a message
// to it starts a new conversation.
export type ChatConversationStatus = 'open' | 'closed';
// Why a conversation closed: an operator closed it (Resolve, Close conversation), the visitor started a new chat, or
// it stayed silent past the desk's close after.
export type ChatCloseReason = 'resolved' | 'ended' | 'inactive';
// A desk's style. Support: a conversation closes on Resolve, on the visitor's "Start a new chat" or after inactivity.
// Ongoing: one long-lived thread per visitor, closed only on request.
export type ChatConversationStyle = 'support' | 'ongoing';
// What happens once a visitor has waited for a person longer than the desk's response time.
export type ChatResponseTimeoutAction = 'handback' | 'overdue' | 'wait';
// `section` of `GET /conversations`; never share a row. Waiting: a visitor waits for a person. In progress: an
// operator holds it and answered last. Bot: the bot still runs it. Those three list open conversations only. Test:
// operators' test conversations, closed ones included. Closed: every other closed conversation with a message.
export type ChatInboxSection = 'waiting' | 'in_progress' | 'bot' | 'test' | 'closed';
// `order` of `GET /conversations`: newest or oldest activity first. Waiting (longest wait first) and Closed (most
// recently closed first) ignore it.
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
    style: ChatConversationStyle;
    // Inactivity rules: how long a visitor may wait for a person and what happens then; and, on Support desks, how
    // long a conversation may stay silent before it closes.
    response_time_seconds: number;
    on_response_timeout: ChatResponseTimeoutAction;
    // Posted to the visitor as the bot's message on a hand back; an empty one posts nothing.
    handback_message: string;
    close_after_seconds: number;
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
    | 'style'
    | 'response_time_seconds'
    | 'on_response_timeout'
> &
    // Left out only on a create that knows nothing for them, while the limits failed to load (close after: on an
    // Ongoing desk, which never uses it): the server's defaults stand. An empty notice would post nothing.
    Partial<Pick<ChatBinding, 'handback_message' | 'close_after_seconds'>>;

// PATCH body: only the keys that changed; the server applies `exclude_unset`.
export type ChatBindingPatch = Partial<ChatBindingInput>;

// What a deployment caps: the token budgets and the inactivity durations.
type ChatBindingCapped = Pick<
    ChatBinding,
    'token_budget_per_conversation' | 'daily_token_budget' | 'response_time_seconds' | 'close_after_seconds'
>;

// `GET /bindings/limits`: the server's create defaults and the caps a binding may not exceed.
export interface ChatBindingLimits {
    defaults: ChatBindingCapped & Pick<ChatBinding, 'on_response_timeout' | 'handback_message' | 'style'>;
    caps: ChatBindingCapped;
}

// Every other create default comes from the server (`GET /bindings/limits`).
export const CHAT_BINDING_DEFAULTS: Omit<
    ChatBindingInput,
    | 'name'
    | 'bot_display_name'
    | 'graph_id'
    | 'token_budget_per_conversation'
    | 'daily_token_budget'
    | 'response_time_seconds'
    | 'on_response_timeout'
    | 'handback_message'
    | 'close_after_seconds'
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
    // Asked on create, preselected so that setting up a desk stays name + flow: the server's default once the limits
    // load, this one until then and when they fail to.
    style: 'support',
};

// Both display names and an operator's alias; the server refuses longer ones (counted in characters, after trimming).
export const CHAT_DISPLAY_NAME_MAX = 64;

// `GET /bindings/my-aliases`: a name the user goes by on one desk instead of the desk's operator display name.
export interface ChatMyAlias {
    binding_id: string;
    alias: string;
}

// `PUT /bindings/{id}/my-alias`: the alias as stored (null once cleared) and the name visitors now see on the user's
// replies there: the alias, else the desk's operator display name.
export interface ChatMyAliasResult {
    binding_id: string;
    alias: string | null;
    visible_name: string;
}

// What a flow lacks for the chat contract, item by item: a start or end node, the start node's Domain variables, the
// end node's `output_map` keys. Nothing missing when it can serve chat.
export interface ChatContractMissing {
    missing_start_node: boolean;
    missing_end_node: boolean;
    start_variables: string[];
    end_outputs: string[];
}

// `GET /bindings/contract?graph_id=`: what keeps a flow from serving chat; empty when it can.
export interface ChatContractCheck {
    contract_errors: string[];
    contract_missing: ChatContractMissing;
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

// One row of `GET /conversations` (and of `GET /conversations/{id}`), the payload of the inbox `conversation.updated`
// event and the answer to claim, release and close.
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
    // operator reply; cleared by an operator reply, a return to the bot or a close (a take over keeps it).
    visitor_waiting_since: string | null;
    status: ChatConversationStatus;
    // Set by the close; null while open. A close keeps the mode and the holder as they were.
    close_reason: ChatCloseReason | null;
    closed_at: string | null;
    // The operator who closed it (a `resolved` close only) and their display name, null when not known yet.
    closed_by_user_id: number | null;
    closed_by_name: string | null;
}

// One conversation the Waiting count includes (`GET /inbox/badges`): its desk and holder, to count per desk and Mine.
export interface ChatInboxBadge {
    id: string;
    binding_id: string;
    assigned_operator_id: number | null;
}

// `GET /inbox/badges`: every open conversation waiting for a person, org-wide; tests never wait, closed conversations
// never count. In progress has no count: nothing closes an answered conversation on an Ongoing desk, so that set
// could only grow.
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
    // The name visitors saw on an operator message, kept as it was sent (the alias, else the desk's operator display
    // name); null on every other message.
    visible_name: string | null;
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
    visible_name: string | null;
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

// Every chat service error body; `retry_after` on 429, `contract_errors` and `contract_missing` on 400
// `contract_failed` (resume), `field` and `max` on 400 `budget_above_cap` and `duration_above_cap` (`max` in the
// field's own unit: tokens, seconds), `close_reason` on 409 `conversation_closed`.
export interface ChatErrorBody {
    code: string;
    message: string;
    retry_after?: number;
    contract_errors?: string[];
    // Null on a `contract_failed` built from stored errors only: then there is no fix to offer.
    contract_missing?: ChatContractMissing | null;
    field?: string;
    max?: number;
    close_reason?: ChatCloseReason;
    // On 400 `validation_error`: what was refused, one entry per problem; `key` names a refused body field.
    errors?: { message: string; key?: string }[];
}
