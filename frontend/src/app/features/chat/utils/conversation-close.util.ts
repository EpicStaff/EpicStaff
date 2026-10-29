import { formatDate } from '@angular/common';
import { HttpErrorResponse } from '@angular/common/http';

import { ChatCloseReason, ChatConversation, ChatConversationStyle, ChatErrorBody } from '../models/chat.model';
import { operatorName } from './conversation-row.util';

type ClosedRow = Pick<ChatConversation, 'close_reason' | 'closed_at' | 'closed_by_user_id' | 'closed_by_name'>;

/** Whether a conversation is closed; a row without the field (an older chat service) is open. */
export function isClosed(row: Pick<ChatConversation, 'status'> | null | undefined): boolean {
    return row?.status === 'closed';
}

/** The server refused an action because the conversation is closed (409): what is shown of it is stale. */
export function isConversationClosed(error: HttpErrorResponse): boolean {
    return (error.error as ChatErrorBody | null)?.code === 'conversation_closed';
}

/**
 * Why a conversation closed, in one word for its row: an operator's close is "Resolved" on a Support desk and "Closed"
 * on any other (Ongoing, or a desk not known yet); the visitor's is "Ended", the timer's "Inactive". Empty without one.
 */
export function closeReasonWord(reason: ChatCloseReason | null, style: ChatConversationStyle | null): string {
    switch (reason) {
        case 'resolved':
            return style === 'support' ? 'Resolved' : 'Closed';
        case 'ended':
            return 'Ended';
        case 'inactive':
            return 'Inactive';
        default:
            return '';
    }
}

/**
 * Why a conversation closed, in words: "Resolved by Mike" on a Support desk, "Closed by Mike" on any other, "you" for
 * the current user and "Operator #7" while the name is not known; "Ended by the visitor"; "Closed after inactivity".
 * Empty without a reason.
 */
export function closeReasonLabel(row: ClosedRow, style: ChatConversationStyle | null, myUserId: number | null): string {
    switch (row.close_reason) {
        case 'resolved':
            return `${closeReasonWord('resolved', style)} by ${closer(row, myUserId)}`;
        case 'ended':
            return 'Ended by the visitor';
        case 'inactive':
            return 'Closed after inactivity';
        default:
            return '';
    }
}

/**
 * The closed thread's banner: "Closed · Resolved by Mike · 14:05", "Closed · Ended by the visitor · Oct 5, 9:00 AM",
 * "Closed after inactivity · 14:05", and on an Ongoing desk "Closed by Mike · 14:05". The time follows `locale`: the
 * clock time for a close today, else the date as well.
 */
export function closedSummary(
    row: ClosedRow,
    style: ChatConversationStyle | null,
    myUserId: number | null,
    now: number,
    locale: string
): string {
    const reason = closeReasonLabel(row, style, myUserId);
    return [reason.startsWith('Closed') ? null : 'Closed', reason, closedTime(row.closed_at, now, locale)]
        .filter(Boolean)
        .join(' · ');
}

// "you", the operator's name, "Operator #7"; a close the server names no operator for is still someone's.
function closer(row: ClosedRow, myUserId: number | null): string {
    const userId = row.closed_by_user_id;
    if (userId === null) return row.closed_by_name || 'an operator';
    return userId === myUserId ? 'you' : operatorName(userId, row.closed_by_name);
}

function closedTime(iso: string | null, now: number, locale: string): string {
    if (!iso) return '';
    const date = new Date(iso);
    const clock = formatDate(date, 'shortTime', locale);
    const today = new Date(now);
    if (date.toDateString() === today.toDateString()) return clock;
    const day = formatDate(date, date.getFullYear() === today.getFullYear() ? 'MMM d' : 'MMM d, y', locale);
    return `${day}, ${clock}`;
}
