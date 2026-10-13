import { ChatConversation, ChatInboxOrder, ChatInboxSection, ChatOperatorMessage } from '../models/chat.model';

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

// The server's section filters, row for row: a conversation is in at most one section, and in none while it has no
// message yet (outside Waiting). `!= null` also reads a field an older payload lacks as empty.
const SECTION_FILTERS: Record<ChatInboxSection, (row: ChatConversation) => boolean> = {
    waiting: (row) => row.visitor_waiting_since != null && !row.is_test,
    in_progress: (row) =>
        row.assigned_operator_id != null &&
        row.visitor_waiting_since == null &&
        row.last_message_at != null &&
        !row.is_test,
    bot: (row) => row.handoff_at == null && row.last_message_at != null && !row.is_test,
    test: (row) => row.is_test && row.last_message_at != null,
};

/** Whether the server lists `row` in `section`; with `holderId` (Mine), only the conversations that user holds. */
export function belongsTo(row: ChatConversation, section: ChatInboxSection, holderId: number | null): boolean {
    if (holderId !== null && row.assigned_operator_id !== holderId) return false;
    return SECTION_FILTERS[section](row);
}

/** Waiting is a queue: always the longest wait first, whatever the chosen order. */
export const isQueue = (section: ChatInboxSection): boolean => section === 'waiting';

/**
 * The API's order for a section: Waiting by wait start, oldest first; the others by latest message, newest or oldest
 * first. Ties break on the id in the same direction, as the server's keyset does.
 */
export function inboxOrder(section: ChatInboxSection, order: ChatInboxOrder): ConversationOrder {
    const key = isQueue(section) ? 'visitor_waiting_since' : 'last_message_at';
    const direction = isQueue(section) || order === 'oldest' ? 1 : -1;
    return (left, right) =>
        direction * (microseconds(left[key]) - microseconds(right[key]) || compareIds(left.id, right.id));
}

/**
 * Replaces or inserts a row in a sorted section list. `boundary` is the last row fetched while more pages remain:
 * a row sorting after it belongs to an unfetched page, so it is dropped here and arrives with that page.
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

/** One row per id; the POST response, the streamed event and a page race, so non-null run and author fields win. */
export function upsertMessage(messages: ChatOperatorMessage[], message: ChatOperatorMessage): ChatOperatorMessage[] {
    const existing = messages.find((item) => item.id === message.id);
    const merged: ChatOperatorMessage = existing
        ? {
              ...existing,
              ...message,
              session_id: message.session_id ?? existing.session_id,
              author_user_id: message.author_user_id ?? existing.author_user_id,
              author_name: message.author_name ?? existing.author_name,
              visible_name: message.visible_name ?? existing.visible_name,
          }
        : message;
    return [...messages.filter((item) => item.id !== message.id), merged].sort(
        (left, right) => microseconds(left.created_at) - microseconds(right.created_at)
    );
}
