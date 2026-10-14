import { RecycleBinPurgedEntry } from '../models/storage.models';

/**
 * Longest purged path quoted in the toast, in characters. The shared toast is 350px wide and clamps
 * to 3 lines; with the fixed sentence around it, a longer path would push the end of the sentence
 * out of view.
 */
export const PURGED_NAME_MAX_LENGTH = 40;

/**
 * Toast text telling the user the quota made the server permanently delete bin entries, or null
 * when nothing was purged. An entry may be a folder, and its name is null when the user can't read
 * files, so the entry is named only when it is the only one and its name is known.
 *
 *  [{ name: 'docs/a.txt', size: 7 }] → 'Storage was full, so "docs/a.txt" was permanently deleted from the recycle bin.'
 *  [{ name: null, size: 7 }]         → 'Storage was full, so the oldest item in the recycle bin was permanently deleted.'
 *  three entries                     → 'Storage was full, so the 3 oldest items in the recycle bin were permanently deleted.'
 */
export function recycleBinPurgeMessage(entries: readonly RecycleBinPurgedEntry[]): string | null {
    if (entries.length === 0) return null;
    if (entries.length === 1) {
        const { name } = entries[0];
        if (name !== null) {
            return `Storage was full, so "${shortenPath(name)}" was permanently deleted from the recycle bin.`;
        }
        return 'Storage was full, so the oldest item in the recycle bin was permanently deleted.';
    }
    return `Storage was full, so the ${entries.length} oldest items in the recycle bin were permanently deleted.`;
}

/**
 * Cuts a long path from the start, so the name at its end stays readable. Counts code points, not
 * UTF-16 units, so an emoji or other astral character is never split in half.
 */
function shortenPath(path: string): string {
    const characters = Array.from(path);
    if (characters.length <= PURGED_NAME_MAX_LENGTH) return path;
    return `…${characters.slice(characters.length - (PURGED_NAME_MAX_LENGTH - 1)).join('')}`;
}
