/**
 * Filters `items` by a case-insensitive substring match against a `selector`.
 *
 * - `query` is lowercased once inside the function; the caller controls trimming.
 * - Returns the full `items` array when the lowercased query is an empty string,
 *   preserving the existing behavior of both call sites.
 */
export function filterByQuery<T>(items: readonly T[], query: string, selector: (item: T) => string): T[] {
    const q = query.toLowerCase();
    if (!q) {
        return items as T[];
    }
    return items.filter((item) => selector(item).toLowerCase().includes(q));
}
