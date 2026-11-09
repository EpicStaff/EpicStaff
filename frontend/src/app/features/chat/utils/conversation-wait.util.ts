import { ChatConversation } from '../models/chat.model';
import { isClosed } from './conversation-close.util';

/** A wait counts the seconds ("12m 16s"), so a clock showing one moves every second. */
export const WAIT_TICK_MS = 1_000;

type WaitFields = Pick<ChatConversation, 'status' | 'visitor_waiting_since' | 'is_test'>;

/**
 * Whether the visitor waits for a person, whether or not someone took the conversation: a visitor message after the
 * last operator reply waits too. Loose on purpose: a conversation without the field (an older chat service) is not
 * waiting. A closed one never waits.
 */
export function isWaitingForPerson(conversation: WaitFields): boolean {
    return !isClosed(conversation) && conversation.visitor_waiting_since != null;
}

/**
 * Waited past the desk's response time (`overdueAfterMs`; null on a desk that marks no one overdue). A test
 * conversation is never overdue.
 */
export function isWaitOverdue(conversation: WaitFields, overdueAfterMs: number | null, now: number): boolean {
    return (
        isWaitingForPerson(conversation) &&
        !conversation.is_test &&
        isOverdue(conversation.visitor_waiting_since, overdueAfterMs, now)
    );
}

/** What an overdue wait's chip says when hovered or focused. */
export const WAIT_OVERDUE_NOTE = "Overdue: waiting longer than the desk's response time";

/**
 * Whether a visitor has waited longer than `overdueAfterMs` (null: the desk marks no one overdue). Exactly the response
 * time is not overdue yet; a missing or unusable time never is.
 */
export function isOverdue(
    waitingSinceIso: string | null | undefined,
    overdueAfterMs: number | null,
    now: number
): boolean {
    if (overdueAfterMs === null) return false;
    const since = waitingSinceIso ? Date.parse(waitingSinceIso) : NaN;
    return !Number.isNaN(since) && now - since > overdueAfterMs;
}
