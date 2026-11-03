/**
 * The item a key moves to in a list: the arrows step and wrap at both ends, Home and End jump to the ends.
 * `current` is -1 while nothing is highlighted, so the first ↓ lands on the first item and ↑ on the last.
 * Returns null for any other key, or an empty list.
 */
export function nextListIndex(key: string, current: number, count: number): number | null {
    if (count === 0) return null;
    switch (key) {
        case 'ArrowDown':
            return current < 0 ? 0 : (current + 1) % count;
        case 'ArrowUp':
            return current < 0 ? count - 1 : (current - 1 + count) % count;
        case 'Home':
            return 0;
        case 'End':
            return count - 1;
        default:
            return null;
    }
}
