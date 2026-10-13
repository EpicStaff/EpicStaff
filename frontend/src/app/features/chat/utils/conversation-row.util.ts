import { formatDate } from '@angular/common';

import { ChatConversation } from '../models/chat.model';
import { deskInitials } from './desk-avatar.util';

const MINUTE = 60_000;
const HOUR = 60 * MINUTE;
const DAY = 24 * HOUR;
// Older than this many calendar days, a time shows as a date rather than a weekday.
const WEEK_DAYS = 7;
// What fits in a row's round avatar.
const AVATAR_DIGITS = 3;

type TimeBucket =
    | { kind: 'now' }
    | { kind: 'minutes'; minutes: number }
    | { kind: 'today'; date: Date }
    | { kind: 'yesterday' }
    | { kind: 'week'; date: Date }
    | { kind: 'older'; date: Date; showYear: boolean };

type VisitorIdentity = Pick<ChatConversation, 'visitor_number' | 'chat_user_id'>;
type LastAuthor = Pick<
    ChatConversation,
    'last_message_role' | 'last_message_author_user_id' | 'last_message_author_name'
>;

/** A signed visitor by the customer id the desk's backend vouched for; anyone else as "Visitor 12" (numbered per desk). */
export function visitorName(row: VisitorIdentity): string {
    return row.chat_user_id || `Visitor ${row.visitor_number}`;
}

/** A signed visitor's initials (the desk pictures' rule); else the visitor number, its last three digits once longer. */
export function visitorAvatarText(row: VisitorIdentity): string {
    if (row.chat_user_id) return deskInitials(row.chat_user_id);
    return String(row.visitor_number).slice(-AVATAR_DIGITS);
}

/** An operator by their display name, or "Operator #7" while the chat service does not know it yet. */
export function operatorName(userId: number, name: string | null): string {
    return name || `Operator #${userId}`;
}

/**
 * Who wrote the last message, shown before its preview: "You:" for the current user, another operator's name, "Bot:".
 * Nothing for the visitor (the row is theirs), a system note (the row mutes it instead) or no message yet.
 */
export function senderPrefix(row: LastAuthor, myUserId: number | null): string | null {
    switch (row.last_message_role) {
        case 'assistant':
            return 'Bot:';
        case 'operator': {
            const authorId = row.last_message_author_user_id;
            if (authorId === null) return 'Operator:';
            return authorId === myUserId ? 'You:' : `${operatorName(authorId, row.last_message_author_name)}:`;
        }
        default:
            return null;
    }
}

/**
 * A row's time, as chat apps show it: "now" (under a minute), "6m" (under an hour), the clock time earlier today
 * ("2:05 PM" in en-US), "Yesterday", a weekday within the last week, else a short date. Clock, weekday and date follow
 * `locale`, as the thread's times do. Empty without a time; a time ahead of `now` (clock skew) is "now".
 */
export function conversationTime(iso: string | null, now: number, locale: string): string {
    if (!iso) return '';
    const bucket = timeBucket(iso, now);
    switch (bucket.kind) {
        case 'now':
            return 'now';
        case 'minutes':
            return `${bucket.minutes}m`;
        case 'today':
            return formatDate(bucket.date, 'shortTime', locale);
        case 'yesterday':
            return 'Yesterday';
        case 'week':
            return formatDate(bucket.date, 'EEE', locale);
        case 'older':
            return formatDate(bucket.date, bucket.showYear ? 'MMM d, y' : 'MMM d', locale);
    }
}

/**
 * The same time in words for a screen reader, absolute so it stays the same while the clock ticks (it changes at
 * midnight only): "today at 2:05 PM", "yesterday at 9:00 AM", "Wednesday at 4:30 PM", "October 5".
 */
export function conversationTimeLabel(iso: string | null, now: number, locale: string): string {
    if (!iso) return '';
    const date = new Date(iso);
    const daysAgo = calendarDaysBetween(date, new Date(now));
    const clock = formatDate(date, 'shortTime', locale);
    if (daysAgo <= 0) return `today at ${clock}`;
    if (daysAgo === 1) return `yesterday at ${clock}`;
    if (daysAgo < WEEK_DAYS) return `${formatDate(date, 'EEEE', locale)} at ${clock}`;
    return formatDate(date, date.getFullYear() === new Date(now).getFullYear() ? 'MMMM d' : 'MMMM d, y', locale);
}

/** How long someone has waited: "<1m", "4m", "1h 5m", "3h", "2d". Empty without a usable time. */
export function waitDuration(sinceIso: string | null | undefined, now: number): string {
    const since = sinceIso ? Date.parse(sinceIso) : NaN;
    if (Number.isNaN(since)) return '';
    const waited = Math.max(0, now - since);
    if (waited < MINUTE) return '<1m';
    if (waited < HOUR) return `${Math.floor(waited / MINUTE)}m`;
    if (waited < DAY) {
        const hours = Math.floor(waited / HOUR);
        const minutes = Math.floor((waited % HOUR) / MINUTE);
        return minutes ? `${hours}h ${minutes}m` : `${hours}h`;
    }
    return `${Math.floor(waited / DAY)}d`;
}

function timeBucket(iso: string, now: number): TimeBucket {
    const date = new Date(iso);
    const elapsed = now - date.getTime();
    if (elapsed < MINUTE) return { kind: 'now' };
    if (elapsed < HOUR) return { kind: 'minutes', minutes: Math.floor(elapsed / MINUTE) };
    const daysAgo = calendarDaysBetween(date, new Date(now));
    if (daysAgo === 0) return { kind: 'today', date };
    if (daysAgo === 1) return { kind: 'yesterday' };
    if (daysAgo < WEEK_DAYS) return { kind: 'week', date };
    return { kind: 'older', date, showYear: date.getFullYear() !== new Date(now).getFullYear() };
}

// Local calendar days, so "Yesterday" follows the user's midnight; rounding absorbs a daylight-saving hour.
function calendarDaysBetween(earlier: Date, later: Date): number {
    const startOfDay = (date: Date): number => new Date(date.getFullYear(), date.getMonth(), date.getDate()).getTime();
    return Math.round((startOfDay(later) - startOfDay(earlier)) / DAY);
}
