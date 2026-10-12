import { ChatConversation, ChatInboxSection, ChatOperatorMessage } from '../models/chat.model';

const ISO_FRACTION = /\.(\d+)/;

/**
 * Microseconds since the epoch. The server orders by microsecond timestamps and `Date` keeps only milliseconds,
 * so the fraction is read from the string. Accepts `…Z` (REST) and `…+00:00` (stream), with 0 to 6 fraction digits.
 */
export function microseconds(value: string | null): number {
    if (!value) return 0;
    const fraction = ISO_FRACTION.exec(value);
    const wholeSeconds = Date.parse(fraction ? value.replace(fraction[0], '') : value);
    return wholeSeconds * 1000 + (fraction ? Number(fraction[1].slice(0, 6).padEnd(6, '0')) : 0);
}

export type ConversationOrder = (left: ChatConversation, right: ChatConversation) => number;

// The server orders by uuid; canonical lowercase uuids compare the same as strings.
const compareIds = (left: string, right: string): number => (left < right ? -1 : left > right ? 1 : 0);

/** A test conversation is only ever in Tests; any other that left bot mode (awaiting or claimed) is in human. */
export function inboxSection(row: ChatConversation): ChatInboxSection {
    if (row.is_test) return 'test';
    return row.mode === 'bot' ? 'bot' : 'human';
}

const newestActivityFirst: ConversationOrder = (left, right) =>
    microseconds(right.last_message_at) - microseconds(left.last_message_at) || compareIds(right.id, left.id);

/**
 * The API orders, per section: human is first-come-first-served by handoff time; bot and test are newest activity
 * first.
 */
export const INBOX_ORDER: Record<ChatInboxSection, ConversationOrder> = {
    human: (left, right) =>
        microseconds(left.handoff_at) - microseconds(right.handoff_at) || compareIds(left.id, right.id),
    bot: newestActivityFirst,
    test: newestActivityFirst,
};

/**
 * Replaces or inserts a row in a sorted section list. `boundary` is the last row fetched while more pages remain:
 * a row sorting after it belongs to an unfetched page, so it is dropped here and arrives with Load more.
 */
export function placeRow(
    list: ChatConversation[],
    row: ChatConversation,
    order: ConversationOrder,
    boundary: ChatConversation | null
): ChatConversation[] {
    const rest = list.filter((item) => item.id !== row.id);
    if (boundary && order(row, boundary) > 0) return rest;
    return [...rest, row].sort(order);
}

/** One row per id; the POST response and the streamed event race, so non-null operator fields win. */
export function upsertMessage(messages: ChatOperatorMessage[], message: ChatOperatorMessage): ChatOperatorMessage[] {
    const existing = messages.find((item) => item.id === message.id);
    const merged: ChatOperatorMessage = existing
        ? {
              ...existing,
              ...message,
              session_id: message.session_id ?? existing.session_id,
              author_user_id: message.author_user_id ?? existing.author_user_id,
          }
        : message;
    return [...messages.filter((item) => item.id !== message.id), merged].sort(
        (left, right) => microseconds(left.created_at) - microseconds(right.created_at)
    );
}
