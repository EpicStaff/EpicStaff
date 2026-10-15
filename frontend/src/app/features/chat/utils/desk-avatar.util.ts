import { CHAT_BINDING_STATUS_LABELS, ChatBindingStatus } from './binding-status.util';

/** The avatar fills, as CSS custom properties defined in `_variables.scss` (the same in both themes). */
export const AVATAR_COLORS: readonly string[] = [
    '--color-avatar-1',
    '--color-avatar-2',
    '--color-avatar-3',
    '--color-avatar-4',
    '--color-avatar-5',
    '--color-avatar-6',
];

/** The picture of All desks, which is not a desk: the sidenav's Conversations icon, as All desks is where its badge leads. */
export const ALL_DESKS_ICON = 'messages';

const BADGE_CAP = 99;
// A letter or digit with the combining marks that follow it, so a decomposed "É" stays one character.
const LETTER_OR_DIGIT = /[\p{L}\p{N}]\p{M}*/gu;
// A name already ending in "desk" is not read as "Support desk desk" or "Helpdesk desk".
const ENDS_WITH_DESK = /desks?$/i;

/**
 * Up to two uppercase characters for a desk's picture: the first letters (or digits) of the first two words, or the
 * first two of a single word. Punctuation and emoji inside a word are skipped ("Q&A" is "QA", "🤖 Bot" is "BO"). A
 * name without any letter or digit keeps its first symbol as written (an emoji stays an emoji); a blank name gives
 * '' and the avatar shows an icon instead.
 */
export function deskInitials(name: string): string {
    const words = name
        .trim()
        .split(/\s+/)
        .map((word) => word.match(LETTER_OR_DIGIT) ?? [])
        .filter((characters) => characters.length > 0);
    if (words.length >= 2) return (words[0][0] + words[1][0]).toUpperCase();
    if (words.length === 1) return words[0].slice(0, 2).join('').toUpperCase();
    return firstGrapheme(name.trim());
}

/** An avatar fill picked by `seed` (a desk or conversation id), always the same one, as a `var(...)` for a style binding. */
export function avatarColor(seed: string): string {
    return `var(${AVATAR_COLORS[hashString(seed) % AVATAR_COLORS.length]})`;
}

/**
 * The fill of a desk's picture, picked by its id: stable across renames, and two desks with the same name still
 * (most likely) differ.
 */
export function deskAvatarColor(deskId: string): string {
    return avatarColor(deskId);
}

/** The badge text: nothing at zero, the count up to 99, then "99+". */
export function deskBadgeText(count: number): string | null {
    if (count <= 0) return null;
    return count > BADGE_CAP ? `${BADGE_CAP}+` : String(count);
}

/**
 * What a screen reader says for a desk's picture, e.g. "Sales desk, Live, 2 waiting for a person". The status and
 * the count are left out when there is none; the count is exact even where the badge shows "99+".
 */
export function deskAccessibleName(name: string, status: ChatBindingStatus | null, count: number): string {
    const trimmed = name.trim();
    const subject = !trimmed ? 'Desk' : ENDS_WITH_DESK.test(trimmed) ? trimmed : `${trimmed} desk`;
    const parts = [subject];
    if (status) parts.push(CHAT_BINDING_STATUS_LABELS[status]);
    if (count > 0) parts.push(`${count} waiting for a person`);
    return parts.join(', ');
}

// Emoji sequences (flags, skin tones, joined emoji) are several code points; a grapheme keeps them whole.
function firstGrapheme(text: string): string {
    const first = new Intl.Segmenter(undefined, { granularity: 'grapheme' }).segment(text)[Symbol.iterator]().next();
    return first.done ? '' : first.value.segment;
}

// 32-bit FNV-1a: cheap, and spreads similar ids (UUIDs differing in one character) across the palette.
function hashString(text: string): number {
    let hash = 0x811c9dc5;
    for (let index = 0; index < text.length; index++) {
        hash ^= text.charCodeAt(index);
        hash = Math.imul(hash, 0x01000193);
    }
    return hash >>> 0;
}
