import { CHAT_DISPLAY_NAME_MAX } from '../models/chat.model';

// The chat service's rules for a name visitors see (a desk's bot and operator names, an operator's alias), mirrored
// for quick feedback. The service decides: its answer is shown as it comes.

// What the service's `str.strip()` strips: Python's whitespace, which is not JavaScript's `trim()` set. It includes the
// information separators U+001C-U+001F and NEL U+0085, which `trim()` keeps (they would then be refused as control
// characters); it excludes the byte order mark U+FEFF, which `trim()` strips (it is refused as a format character).
const PYTHON_WHITESPACE =
    '[\\t\\n\\v\\f\\r\\x1c-\\x20\\x85\\xa0\\u1680\\u2000-\\u200a\\u2028\\u2029\\u202f\\u205f\\u3000]';
const PYTHON_STRIP = new RegExp(`^${PYTHON_WHITESPACE}+|${PYTHON_WHITESPACE}+$`, 'g');

// Kept although invisible, because emoji need them: the zero width joiner builds sequences, and variation selectors
// 15 and 16 pick text or emoji style.
const EMOJI_JOINERS: ReadonlySet<number> = new Set([0x200d, 0xfe0e, 0xfe0f]);
// Refused by kind: controls, surrogates, private use, unassigned, line and paragraph separators, and invisible
// formatting (the bidirectional overrides among it). Unassigned follows this browser's Unicode version, which may
// differ from the service's for the newest characters.
const REFUSED_KIND = /[\p{Cc}\p{Cs}\p{Co}\p{Cn}\p{Zl}\p{Zp}\p{Cf}]/u;
// Refused one by one: characters of allowed kinds that render as nothing or as a blank.
const INVISIBLE_FILLERS: readonly (readonly [number, number])[] = [
    [0x034f, 0x034f], // combining grapheme joiner
    [0x115f, 0x1160], // Hangul choseong and jungseong fillers
    [0x17b4, 0x17b5], // Khmer inherent vowels
    [0x180b, 0x180f], // Mongolian free variation selectors and vowel separator
    [0x2800, 0x2800], // braille pattern blank
    [0x3164, 0x3164], // Hangul filler
    [0xffa0, 0xffa0], // halfwidth Hangul filler
    [0xfe00, 0xfe0d], // variation selectors 1-14 (15 and 16 are emoji joiners)
    [0x1bca0, 0x1bca3], // shorthand format controls
    [0x1d173, 0x1d17a], // musical symbol formatting
    [0xe0000, 0xe0fff], // tags, variation selectors 17-256 and their reserved block
];
// Pydantic's prefix on a validator's own message in a `validation_error`: the rest is written for people.
const VALIDATOR_PREFIX = /^Value error, /;
// Full case folding turns these into "ss"; `toLowerCase()` does not (U+1E9E lowers to U+00DF first).
const FOLDS_TO_SS = /[ßẞ]/g;

/** A name as the service stores it: in composed form (NFC), then stripped as it strips. Empty means blank. */
export function normalizePublicName(text: string): string {
    return text.normalize('NFC').replace(PYTHON_STRIP, '');
}

/** Whether a name visitors see may not contain this character (one code point). */
export function isRefusedInPublicName(character: string): boolean {
    const codePoint = character.codePointAt(0) ?? 0;
    if (EMOJI_JOINERS.has(codePoint)) return false;
    return (
        INVISIBLE_FILLERS.some(([first, last]) => codePoint >= first && codePoint <= last) ||
        REFUSED_KIND.test(character)
    );
}

/**
 * What the service would refuse in a normalised, non-blank name, said for people; null when it would take it. The
 * length counts characters (code points), not UTF-16 units.
 */
export function publicNameError(name: string): string | null {
    const characters = [...name];
    if (characters.length > CHAT_DISPLAY_NAME_MAX) return `Use at most ${CHAT_DISPLAY_NAME_MAX} characters.`;
    const refused = characters.find(isRefusedInPublicName);
    if (refused === undefined) return null;
    const codePoint = (refused.codePointAt(0) ?? 0).toString(16).toUpperCase().padStart(4, '0');
    return `Remove the invisible or control character U+${codePoint}: visitors would not see it.`;
}

/**
 * What two names visitors would read as one have in common, as near to the service's key as JavaScript gets: the emoji
 * joiners dropped, then NFC, case folded, NFC. JavaScript has no full case folding, so lower case stands in for it,
 * with "ß" and "ẞ" folded to "ss" as the service folds them; the rare other differences are left to the service.
 */
export function publicNameKey(name: string): string {
    const visible = [...name].filter((character) => !EMOJI_JOINERS.has(character.codePointAt(0) ?? 0)).join('');
    return visible.normalize('NFC').toLowerCase().replace(FOLDS_TO_SS, 'ss').normalize('NFC');
}

/** A `validation_error` entry's message as people read it: without Pydantic's "Value error, " prefix. */
export function validationReason(message: string): string {
    return message.replace(VALIDATOR_PREFIX, '');
}

/** Whether visitors would read two names as one. */
export function isSamePublicName(first: string, second: string): boolean {
    return publicNameKey(first) === publicNameKey(second);
}
