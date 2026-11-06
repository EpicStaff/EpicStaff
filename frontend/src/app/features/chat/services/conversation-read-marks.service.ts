import { computed, inject, Injectable, linkedSignal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { filter, fromEvent } from 'rxjs';

import { ProfileService } from '../../../services/auth/profile.service';
import { ChatConversation } from '../models/chat.model';

const STORAGE_PREFIX = 'chat:readMarks:';
// The newest marks kept. Dropping older ones moves the baseline past them, so they still read as read.
const MAX_MARKS = 500;

/** One user's marks in this browser: up to when everything counts as read, and the last message seen per conversation. */
interface ReadMarks {
    /**
     * Anything last written up to this time counts as read: set when marks begin, so a first visit does not light up
     * every row, and moved on past the marks dropped to keep the newest. Taken from this browser's clock, compared with
     * the server's message times: a clock that is off moves the baseline by as much.
     */
    since: string;
    seen: Record<string, string>;
}

/**
 * Which conversations have news the current user has not opened, remembered per browser and per user: the chat service
 * keeps no read state. A conversation is read up to its last message once it is open; one whose last message is the
 * user's own never has news. Tabs share the marks: each write merges with what another tab stored, and a change made
 * in another tab shows here at once. Every storage access may throw (private mode, quota): the marks then hold in
 * memory only.
 */
@Injectable({ providedIn: 'root' })
export class ConversationReadMarksService {
    private readonly profileService = inject(ProfileService);
    private readonly userId = computed(() => this.profileService.currentUserSignal()?.id ?? null);
    private readonly marks = linkedSignal<number | null, ReadMarks | null>({
        source: this.userId,
        computation: (userId) => (userId === null ? null : (readStoredMarks(userId) ?? beginMarks(userId))),
    });

    constructor() {
        fromEvent<StorageEvent>(window, 'storage')
            .pipe(
                filter(({ key }) => this.userId() !== null && key === STORAGE_PREFIX + this.userId()),
                takeUntilDestroyed()
            )
            .subscribe(() => {
                const stored = readStoredMarks(this.userId()!);
                if (stored) this.marks.set(stored);
            });
    }

    /** Its last message came after the user last had it open, and is not the user's own. Reads signals only. */
    isUnread(conversation: ChatConversation): boolean {
        const marks = this.marks();
        const lastMessageAt = conversation.last_message_at;
        if (!marks || !lastMessageAt) return false;
        if (conversation.last_message_author_user_id === this.userId()) return false;
        return Date.parse(lastMessageAt) > Date.parse(marks.seen[conversation.id] ?? marks.since);
    }

    /** The user has it open: read up to its last message. */
    markRead(conversation: ChatConversation): void {
        const marks = this.marks();
        const userId = this.userId();
        const lastMessageAt = conversation.last_message_at;
        if (!marks || userId === null || !lastMessageAt || marks.seen[conversation.id] === lastMessageAt) return;
        // Another tab may have stored marks this one has not seen: both are kept.
        const merged = mergeMarks(readStoredMarks(userId) ?? marks, marks);
        const next = keepNewest({ since: merged.since, seen: { ...merged.seen, [conversation.id]: lastMessageAt } });
        this.marks.set(next);
        writeMarks(userId, next);
    }
}

const later = (first: string, second: string): string => (Date.parse(second) > Date.parse(first) ? second : first);

function mergeMarks(first: ReadMarks, second: ReadMarks): ReadMarks {
    const seen = { ...first.seen };
    Object.entries(second.seen).forEach(([id, at]) => (seen[id] = seen[id] ? later(seen[id], at) : at));
    return { since: later(first.since, second.since), seen };
}

function keepNewest(marks: ReadMarks): ReadMarks {
    const entries = Object.entries(marks.seen);
    if (entries.length <= MAX_MARKS) return marks;
    entries.sort(([, first], [, second]) => Date.parse(second) - Date.parse(first));
    const dropped = entries.slice(MAX_MARKS);
    return {
        since: dropped.reduce((since, [, at]) => later(since, at), marks.since),
        seen: Object.fromEntries(entries.slice(0, MAX_MARKS)),
    };
}

function readStoredMarks(userId: number): ReadMarks | null {
    try {
        const value: unknown = JSON.parse(localStorage.getItem(STORAGE_PREFIX + userId) ?? 'null');
        return isReadMarks(value) ? value : null;
    } catch {
        // Unreadable or unavailable: as if nothing were stored.
        return null;
    }
}

// Stored at once, so the baseline holds across reloads and other tabs begin from the same one.
function beginMarks(userId: number): ReadMarks {
    const marks: ReadMarks = { since: new Date().toISOString(), seen: {} };
    writeMarks(userId, marks);
    return marks;
}

function writeMarks(userId: number, marks: ReadMarks): void {
    try {
        localStorage.setItem(STORAGE_PREFIX + userId, JSON.stringify(marks));
    } catch {
        // localStorage unavailable (quota exceeded, private mode): the marks still hold in memory.
    }
}

function isReadMarks(value: unknown): value is ReadMarks {
    if (!value || typeof value !== 'object') return false;
    const { since, seen } = value as Record<string, unknown>;
    return (
        typeof since === 'string' &&
        !Number.isNaN(Date.parse(since)) &&
        !!seen &&
        typeof seen === 'object' &&
        !Array.isArray(seen) &&
        Object.values(seen).every((at) => typeof at === 'string')
    );
}
