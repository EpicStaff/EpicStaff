/**
 * The conversation record the Chat Admin flow writes to its key-value table (one row per
 * conversation, key = conversation id). The app only reads it.
 */

/** Access-list aliases from the plugin's `plugin.json`. */
export const CHAT_FLOW_ALIAS = 'chat';
export const CONVERSATIONS_TABLE_ALIAS = 'conversations';

export const MAX_QUESTION_LENGTH = 4000;
export const CONVERSATIONS_PAGE_SIZE = 20;

export type ConversationRole = 'user' | 'assistant';

export interface ConversationMessage {
    role: ConversationRole;
    content: string;
    /** ISO-8601; empty when unknown. */
    at: string;
}

export interface Conversation {
    conversationId: string;
    title: string;
    turns: number;
    messages: ConversationMessage[];
    startedAt: string | null;
    updatedAt: string | null;
}

/** One row of the conversations list: what the 200-character preview reveals. */
export interface ConversationSummary {
    key: string;
    title: string | null;
    turns: number | null;
    updatedAt: string | null;
}

export interface ConversationPage {
    count: number;
    items: ConversationSummary[];
}

export type ConversationOrdering = 'key' | '-key' | 'updated_at' | '-updated_at';

export const CONVERSATION_ORDERINGS: ReadonlyArray<{ value: ConversationOrdering; label: string }> = [
    { value: '-updated_at', label: 'Recently updated' },
    { value: 'updated_at', label: 'Least recently updated' },
    { value: 'key', label: 'Key, A to Z' },
    { value: '-key', label: 'Key, Z to A' },
];

export const DEFAULT_CONVERSATION_ORDERING: ConversationOrdering = '-updated_at';

export interface ConversationListQuery {
    search: string;
    ordering: ConversationOrdering;
    /** 1-based. */
    page: number;
}

const CONVERSATION_ID_PATTERN = /^c_[0-9a-f]{24}$/;
const KEY_PATTERN = /^[A-Za-z_][A-Za-z0-9_]*$/;
const MAX_KEY_LENGTH = 512;

/** A new conversation id: `c_` + 24 random hex characters. */
export function newConversationId(): string {
    const bytes = crypto.getRandomValues(new Uint8Array(12));
    return 'c_' + Array.from(bytes, (byte) => byte.toString(16).padStart(2, '0')).join('');
}

export function isConversationId(value: string): boolean {
    return CONVERSATION_ID_PATTERN.test(value);
}

/** True for any key the key-value table can hold (`kv.get` refuses others). */
export function isTableKey(value: string): boolean {
    return value.length <= MAX_KEY_LENGTH && KEY_PATTERN.test(value);
}

export function isConversationOrdering(value: unknown): value is ConversationOrdering {
    return CONVERSATION_ORDERINGS.some((option) => option.value === value);
}

/** Reads a stored record; `null` when the value is not a conversation record. */
export function parseConversation(key: string, value: unknown): Conversation | null {
    if (!isRecord(value) || !Array.isArray(value['messages'])) return null;
    const messages = value['messages'].flatMap(parseMessage);
    const title =
        typeof value['title'] === 'string' && value['title'] !== '' ? value['title'] : firstQuestion(messages);
    return {
        conversationId: typeof value['conversation_id'] === 'string' ? value['conversation_id'] : key,
        title,
        turns:
            typeof value['turns'] === 'number'
                ? value['turns']
                : messages.filter((message) => message.role === 'user').length,
        messages,
        startedAt: validTimestamp(value['started_at']),
        updatedAt: validTimestamp(value['updated_at']),
    };
}

/**
 * The value when it is a timestamp `Date` can read, else `null`. The record comes from a flow, so
 * a malformed date must not reach `DatePipe`, which throws on one and would break the render.
 */
export function validTimestamp(value: unknown): string | null {
    return typeof value === 'string' && !Number.isNaN(Date.parse(value)) ? value : null;
}

const PREVIEW_TITLE = /^\{\s*"title"\s*:\s*("(?:[^"\\]|\\.)*")/;
const PREVIEW_TURNS = /"turns"\s*:\s*(\d+)/;

/**
 * Title and turns from a `value_preview` (the first 200 characters of the stored JSON). A long
 * record's preview is cut mid-way, so when it does not parse as a whole, the leading `title` and
 * `turns` are read from the text: Postgres prints `jsonb` keys shortest first, so both come first.
 */
export function summarizePreview(preview: string): { title: string | null; turns: number | null } {
    try {
        const value: unknown = JSON.parse(preview);
        if (isRecord(value)) {
            return {
                title: typeof value['title'] === 'string' ? value['title'] : null,
                turns: typeof value['turns'] === 'number' ? value['turns'] : null,
            };
        }
        return { title: null, turns: null };
    } catch {
        const titleMatch = PREVIEW_TITLE.exec(preview);
        const turnsMatch = PREVIEW_TURNS.exec(preview);
        let title: string | null = null;
        if (titleMatch?.[1]) {
            try {
                title = JSON.parse(titleMatch[1]) as string;
            } catch {
                title = null;
            }
        }
        return { title, turns: turnsMatch?.[1] ? Number(turnsMatch[1]) : null };
    }
}

function parseMessage(raw: unknown): ConversationMessage[] {
    if (!isRecord(raw)) return [];
    const role = raw['role'];
    if ((role !== 'user' && role !== 'assistant') || typeof raw['content'] !== 'string') return [];
    return [{ role, content: raw['content'], at: validTimestamp(raw['at']) ?? '' }];
}

function firstQuestion(messages: readonly ConversationMessage[]): string {
    const question = messages.find((message) => message.role === 'user')?.content ?? '';
    return question.length > 80 ? `${question.slice(0, 79)}…` : question;
}

function isRecord(value: unknown): value is Record<string, unknown> {
    return typeof value === 'object' && value !== null && !Array.isArray(value);
}
