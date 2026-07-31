export function getRelativeTime(date: unknown): string {
    if (!(date instanceof Date)) return '';
    const diffMs = Date.now() - date.getTime();
    const diffMins = Math.floor(diffMs / 60000);
    if (diffMins < 1) return 'Just now';
    if (diffMins < 60) return `${diffMins} m ago`;
    const diffHours = Math.floor(diffMins / 60);
    if (diffHours < 24) return `${diffHours} h ago`;
    const diffDays = Math.floor(diffHours / 24);
    if (diffDays < 30) return `${diffDays} d ago`;
    // "mo", not "m" — this branch is months, and "m" is already minutes above.
    return `${Math.floor(diffDays / 30)} mo ago`;
}
