/**
 * Whole-day distance between today (local midnight) and the target date (local midnight).
 * Positive when the target is in the future, negative when in the past, `0` for today.
 */
export function daysUntil(value: Date | string): number {
    const now = new Date();
    now.setHours(0, 0, 0, 0);
    const target = value instanceof Date ? new Date(value) : new Date(value);
    target.setHours(0, 0, 0, 0);
    const msPerDay = 1000 * 60 * 60 * 24;
    return Math.round((target.getTime() - now.getTime()) / msPerDay);
}
