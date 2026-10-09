/**
 * Up to two uppercase initials for a person's name: the first letters of the first two words,
 * or the first two letters of a single word. Empty when there is no usable name, so the caller
 * can show a placeholder instead of guessing.
 */
export function getUserInitials(name: string | null): string {
    const words = (name ?? '').trim().split(/\s+/).filter(Boolean);
    if (words.length === 0) {
        return '';
    }
    if (words.length === 1) {
        return Array.from(words[0]).slice(0, 2).join('').toUpperCase();
    }
    return (firstCharacter(words[0]) + firstCharacter(words[1])).toUpperCase();
}

function firstCharacter(word: string): string {
    return Array.from(word)[0] ?? '';
}
