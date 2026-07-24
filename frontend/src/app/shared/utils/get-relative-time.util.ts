/**
 * Formats a past date/timestamp as a relative-time label:
 * `just now`, `Nm ago`, `Nh ago`, `1 day ago` / `N days ago`,
 * `1 month ago` / `N months ago`, `1 year ago` / `N years ago`.
 *
 * Returns an em dash (`—`) when the input is `null`, `undefined`, or an invalid date.
 */
export function getRelativeTime(value: Date | string | null | undefined): string {
    if (value === null || value === undefined) return '—';
    const date = value instanceof Date ? value : new Date(value);
    const time = date.getTime();
    if (Number.isNaN(time)) return '—';

    const diffMs = Date.now() - time;
    if (diffMs < 60_000) return 'just now';
    const min = Math.floor(diffMs / 60_000);
    if (min < 60) return `${min}m ago`;
    const hr = Math.floor(min / 60);
    if (hr < 24) return `${hr}h ago`;
    const days = Math.floor(hr / 24);
    if (days < 30) return days === 1 ? '1 day ago' : `${days} days ago`;
    const months = Math.floor(days / 30);
    if (months < 12) return months === 1 ? '1 month ago' : `${months} months ago`;
    const years = Math.floor(months / 12);
    return years === 1 ? '1 year ago' : `${years} years ago`;
}
