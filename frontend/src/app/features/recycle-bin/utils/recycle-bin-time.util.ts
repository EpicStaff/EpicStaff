const MINUTE_MS = 60_000;
const HOUR_MS = 60 * MINUTE_MS;
const DAY_MS = 24 * HOUR_MS;

/** When the nightly purge may remove an item deleted at `deletedAt`. */
export function purgeDate(deletedAt: Date, retentionDays: number): Date {
    return new Date(deletedAt.getTime() + retentionDays * DAY_MS);
}

/**
 * Time left before the purge, precise enough to visibly count down:
 * "6 d 5 h", then "5 h" and "45 min" on the last day, "Any moment now" once due.
 */
export function timeLeftLabel(deletedAt: Date, retentionDays: number, now: Date = new Date()): string {
    const remainingMs = purgeDate(deletedAt, retentionDays).getTime() - now.getTime();
    if (remainingMs < MINUTE_MS) return 'Any moment now';
    const days = Math.floor(remainingMs / DAY_MS);
    const hours = Math.floor((remainingMs % DAY_MS) / HOUR_MS);
    if (days > 0) return hours > 0 ? `${days} d ${hours} h` : `${days} d`;
    if (hours > 0) return `${hours} h`;
    return `${Math.floor(remainingMs / MINUTE_MS)} min`;
}
