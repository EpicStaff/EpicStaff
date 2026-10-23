import { FRAME_LIMITS, NAV_PATH_PATTERN } from './protocol.js';

const PATH_SAFE = /[A-Za-z0-9\-._~]/;
const QUERY_SAFE = /[A-Za-z0-9\-._~=&+]/;
const HEX_PAIR = /^[0-9A-Fa-f]{2}$/;

/** How the plugin page keeps its route: in the address path (`/forecast?city=Berlin`) or in the hash (`#/forecast`). */
export type RoutingMode = 'pathname' | 'hash';

/**
 * True for a path EpicStaff accepts: the grammar of {@link NAV_PATH_PATTERN}, at most 1024 characters, every `%`
 * escape decodable as UTF-8, and no `.` or `..` segment, before or after decoding.
 */
export function isValidNavPath(path: unknown): path is string {
    if (typeof path !== 'string' || path.length > FRAME_LIMITS.maxNavPathLength || !NAV_PATH_PATTERN.test(path)) {
        return false;
    }
    const { pathname, query } = splitQuery(path);
    for (const segment of pathname.split('/').slice(1)) {
        if (segment === '') continue;
        const decoded = decodeNavComponent(segment);
        if (decoded === null || isDotSegment(segment) || isDotSegment(decoded)) return false;
    }
    for (const part of query.split('&')) {
        // A param without a name is dropped, as EpicStaff's router drops it.
        if (part === '' || part.startsWith('=')) continue;
        if (decodeNavComponent(part.replaceAll('+', '%20')) === null) return false;
    }
    return true;
}

/**
 * The one canonical spelling of a navigation path — the one EpicStaff uses — or `null` when the path breaks the
 * grammar. Every segment, query key and query value is decoded (`+` in the query is a space) and re-encoded with every
 * character outside `A-Z a-z 0-9 - . _ ~` as uppercase `%XX`. A repeated query key keeps all its values, grouped at its
 * first position (integer-like keys first, as in a JavaScript object); a param without a name is dropped.
 *
 * Two paths that mean the same page give the same string, so comparing canonical paths is what stops navigation
 * echoes between the plugin page and EpicStaff.
 */
export function canonicalNavPath(path: unknown): string | null {
    if (!isValidNavPath(path)) return null;
    const { pathname, query } = splitQuery(path);

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
        // Ordered like EpicStaff, which keeps the params in a plain object: integer-like keys come first in numeric
        // order, then the others in first-seen order.
        const pairs = Object.entries(Object.fromEntries(params)).flatMap(([key, values]) =>
            values.map((value) => `${encodeComponent(key)}=${encodeComponent(value)}`)
        );
        if (pairs.length > 0) canonical += '?' + pairs.join('&');
    } catch {
        // `encodeURIComponent` throws on a lone surrogate.
        return null;
    }
    return isValidNavPath(canonical) ? canonical : null;
}

/**
 * Turns an address path and query (`location.pathname` and `location.search`) into its canonical navigation path, or
 * `null` when it has none. Characters outside the grammar are percent-encoded first and empty segments are dropped.
 */
export function addressToNavPath(pathname: string, search: string): string | null {
    const query = search.startsWith('?') ? search.slice(1) : search;
    return toNavPath(pathname, query);
}

/**
 * Turns a hash route (`location.hash`, for example `#/forecast?city=New York`) into its canonical navigation path
 * (`/forecast?city=New%20York`), or `null` when it has none. A second `#` and everything after it is dropped.
 */
export function hashToNavPath(hash: string): string | null {
    let route = hash.startsWith('#') ? hash.slice(1) : hash;
    const fragmentStart = route.indexOf('#');
    if (fragmentStart >= 0) route = route.slice(0, fragmentStart);
    const queryStart = route.indexOf('?');
    return queryStart >= 0 ? toNavPath(route.slice(0, queryStart), route.slice(queryStart + 1)) : toNavPath(route, '');
}

/** The navigation path a location shows in the given routing mode, or `null` when it has none. */
export function locationToNavPath(
    location: Pick<Location, 'pathname' | 'search' | 'hash'>,
    mode: RoutingMode
): string | null {
    return mode === 'hash' ? hashToNavPath(location.hash) : addressToNavPath(location.pathname, location.search);
}

/** `decodeURIComponent`, or `null` for a malformed escape or invalid UTF-8. */
export function decodeNavComponent(text: string): string | null {
    try {
        return decodeURIComponent(text);
    } catch {
        return null;
    }
}

function toNavPath(pathname: string, query: string): string | null {
    const segments = pathname.split('/').filter((segment) => segment !== '');
    let path = '/' + segments.map((segment) => encodeOutside(segment, PATH_SAFE)).join('/');
    if (query !== '') path += '?' + encodeOutside(query, QUERY_SAFE);
    return canonicalNavPath(path);
}

function splitQuery(path: string): { pathname: string; query: string } {
    const queryStart = path.indexOf('?');
    return queryStart === -1
        ? { pathname: path, query: '' }
        : { pathname: path.slice(0, queryStart), query: path.slice(queryStart + 1) };
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

function isDotSegment(segment: string): boolean {
    return segment === '.' || segment === '..';
}
