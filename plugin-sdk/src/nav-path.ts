import { decodeNavComponent, isValidNavPath } from './protocol.js';

const PATH_SAFE = /[A-Za-z0-9\-._~]/;
const QUERY_SAFE = /[A-Za-z0-9\-._~=&+]/;
const HEX_PAIR = /^[0-9A-Fa-f]{2}$/;

/**
 * The one canonical spelling of a nav path — the same EpicStaff uses — or `null` when the path
 * breaks the grammar. Every segment, query key and query value is decoded (`+` in the query is a
 * space) and re-encoded with every character outside `A-Z a-z 0-9 - . _ ~` as uppercase `%XX`;
 * a repeated query key keeps all its values, grouped at its first position (integer-like keys
 * first, as in a JavaScript object); a param without a name is dropped. Two paths that mean the same page give the same string, so comparing canonical
 * paths is what stops navigation echoes between the app and EpicStaff.
 */
export function canonicalNavPath(path: unknown): string | null {
    if (!isValidNavPath(path)) return null;
    const queryStart = path.indexOf('?');
    const pathname = queryStart === -1 ? path : path.slice(0, queryStart);
    const query = queryStart === -1 ? '' : path.slice(queryStart + 1);

    const segments = pathname
        .split('/')
        .filter((segment) => segment !== '')
        .map((segment) => decodeNavComponent(segment) ?? '');
    const params = new Map<string, string[]>();
    for (const part of query.split('&')) {
        if (part === '') continue;
        const separator = part.indexOf('=');
        const rawKey = separator === -1 ? part : part.slice(0, separator);
        if (rawKey === '') continue;
        const key = decodeNavComponent(rawKey.replaceAll('+', '%20')) ?? '';
        const value =
            separator === -1 ? '' : (decodeNavComponent(part.slice(separator + 1).replaceAll('+', '%20')) ?? '');
        params.set(key, [...(params.get(key) ?? []), value]);
    }

    let canonical: string;
    try {
        canonical = '/' + segments.map(encodeComponent).join('/');
        // Ordered like EpicStaff, which keeps the params in a plain object: integer-like keys
        // ("0", "1", …) come first in numeric order, then the others in first-seen order.
        const ordered = Object.entries(Object.fromEntries(params));
        const pairs = ordered.flatMap(([key, values]) =>
            values.map((value) => `${encodeComponent(key)}=${encodeComponent(value)}`)
        );
        if (pairs.length > 0) canonical += '?' + pairs.join('&');
    } catch {
        return null;
    }
    return isValidNavPath(canonical) ? canonical : null;
}

/**
 * Turns a hash route (`location.hash`, e.g. `#/conversations/c_1?search=a b`) into its canonical
 * nav path (`/conversations/c_1?search=a%20b`), or `null` when it has none.
 *
 * Characters outside the grammar are percent-encoded first, empty segments are dropped, a second
 * `#` and everything after it is dropped. A `.` or `..` segment, or a path over 1024 characters,
 * has no canonical form.
 */
export function hashToNavPath(hash: string): string | null {
    let route = hash.startsWith('#') ? hash.slice(1) : hash;
    const fragmentStart = route.indexOf('#');
    if (fragmentStart >= 0) route = route.slice(0, fragmentStart);

    const queryStart = route.indexOf('?');
    const pathname = queryStart >= 0 ? route.slice(0, queryStart) : route;
    const query = queryStart >= 0 ? route.slice(queryStart + 1) : '';

    const segments = pathname.split('/').filter((segment) => segment !== '');
    let path = '/' + segments.map((segment) => encodeOutside(segment, PATH_SAFE)).join('/');
    if (query !== '') path += '?' + encodeOutside(query, QUERY_SAFE);
    return canonicalNavPath(path);
}

/** `encodeURIComponent`, plus the five characters it leaves that the grammar does not allow. */
function encodeComponent(text: string): string {
    return encodeURIComponent(text).replace(
        /[!'()*]/g,
        (character) => `%${character.charCodeAt(0).toString(16).toUpperCase()}`
    );
}

/** Percent-encodes every character that `safe` does not match; keeps valid `%XX` escapes. */
function encodeOutside(text: string, safe: RegExp): string {
    let result = '';
    const characters = Array.from(text);
    for (let index = 0; index < characters.length; index++) {
        const character = characters[index] ?? '';
        if (safe.test(character)) {
            result += character;
        } else if (character === '%' && HEX_PAIR.test((characters[index + 1] ?? '') + (characters[index + 2] ?? ''))) {
            result += character;
        } else {
            result += percentEncode(character);
        }
    }
    return result;
}

function percentEncode(character: string): string {
    const bytes = new TextEncoder().encode(character);
    return Array.from(bytes, (byte) => '%' + byte.toString(16).toUpperCase().padStart(2, '0')).join('');
}
