import { BRIDGE_V2_LIMITS } from './bridge-protocol';

/**
 * A plugin page's own path (bridge v2 `nav.*`), in the form EpicStaff's router takes it: decoded
 * path segments and query params. The plugin page lives at `/plugins/<id>/<segments>?<query>`.
 */
export interface PluginNavTarget {
    readonly segments: string[];
    /** Insertion-ordered; a repeated key holds every value, like Angular's own URL parser. */
    readonly queryParams: Record<string, string | string[]>;
}

/** The path a page opens at when the address names nothing below the plugin. */
export const PLUGIN_ROOT_NAV_PATH = '/';

/**
 * The path grammar of bridge v2 (§1.5 of the plugin apps plan): an absolute path of non-empty
 * segments of unreserved characters and `%` escapes, and an optional query of the same plus
 * `=`, `&`, `+`. No fragment, no `.` / `..` segments (checked separately, before and after decoding).
 */
const NAV_PATH_PATTERN = /^\/([A-Za-z0-9\-._~%]+(\/[A-Za-z0-9\-._~%]+)*)?(\?[A-Za-z0-9\-._~%=&+]*)?$/;

/**
 * Parses a path a plugin page reported, or `null` when it breaks the grammar: too long, a `.` or
 * `..` segment (also when `%`-encoded, so the address bar can't be made to climb out of
 * `/plugins/<id>/`), or a malformed `%` escape. `+` in the query means a space, as in the router.
 */
export function parseNavPath(path: unknown): PluginNavTarget | null {
    if (typeof path !== 'string' || path.length > BRIDGE_V2_LIMITS.maxNavPathLength) return null;
    if (!NAV_PATH_PATTERN.test(path)) return null;

    const queryStart = path.indexOf('?');
    const pathname = queryStart === -1 ? path : path.slice(0, queryStart);
    const query = queryStart === -1 ? '' : path.slice(queryStart + 1);

    const segments: string[] = [];
    for (const rawSegment of pathname.split('/').slice(1)) {
        // Only the root path ("/") has an empty segment; the grammar allows no other.
        if (rawSegment === '') continue;
        const segment = decodeComponent(rawSegment);
        if (segment === null || isDotSegment(rawSegment) || isDotSegment(segment)) return null;
        segments.push(segment);
    }

    const queryParams = parseQuery(query);
    return queryParams === null ? null : { segments, queryParams };
}

/**
 * The one canonical spelling of a target: every character outside `A-Z a-z 0-9 - . _ ~` is
 * `%`-encoded (uppercase hex), query keys keep their order. Two paths that mean the same page
 * format to the same string, so the host can tell a real address change from its own echo.
 */
export function formatNavPath(target: PluginNavTarget): string {
    const path = `/${target.segments.map(encodeComponent).join('/')}`;
    const query = Object.entries(target.queryParams)
        .flatMap(([key, value]) =>
            (Array.isArray(value) ? value : [value]).map(
                (item) => `${encodeComponent(key)}=${encodeComponent(String(item))}`
            )
        )
        .join('&');
    return query ? `${path}?${query}` : path;
}

/** The canonical form of a path a plugin page reported, or `null` when it breaks the grammar. */
export function canonicalNavPath(path: unknown): string | null {
    const target = parseNavPath(path);
    if (!target) return null;
    return toValidNavPath(target);
}

/**
 * The canonical path of what EpicStaff's router holds below `/plugins/<id>/` (decoded segments and
 * query params), or {@link PLUGIN_ROOT_NAV_PATH} when that can't be told to a page: too long, a dot
 * segment, or text that can't be encoded. Matrix params are not part of a plugin path.
 */
export function navPathFromRoute(segments: readonly string[], queryParams: Readonly<Record<string, unknown>>): string {
    // `Object.fromEntries` defines own properties, so a `__proto__` key can't touch the prototype.
    const params: Record<string, string | string[]> = Object.fromEntries(
        Object.entries(queryParams)
            .filter(([, value]) => value !== undefined && value !== null)
            .map(([key, value]) => [key, Array.isArray(value) ? value.map(String) : String(value)])
    );
    return toValidNavPath({ segments: [...segments], queryParams: params }) ?? PLUGIN_ROOT_NAV_PATH;
}

/** Formats a target and checks the result is itself a valid path (length, dot segments). */
function toValidNavPath(target: PluginNavTarget): string | null {
    let path: string;
    try {
        path = formatNavPath(target);
    } catch {
        // `encodeURIComponent` throws on a lone surrogate.
        return null;
    }
    return parseNavPath(path) ? path : null;
}

function parseQuery(query: string): Record<string, string | string[]> | null {
    // Built as a Map, then copied with `Object.fromEntries`, so a key such as `__proto__` becomes an
    // own property instead of touching the prototype. A repeated key collects every value in order.
    const params = new Map<string, string | string[]>();
    for (const part of query.split('&')) {
        if (part === '') continue;
        const separator = part.indexOf('=');
        const rawKey = separator === -1 ? part : part.slice(0, separator);
        // The router drops a param without a name; so does the bridge.
        if (rawKey === '') continue;
        const key = decodeQueryComponent(rawKey);
        const value = separator === -1 ? '' : decodeQueryComponent(part.slice(separator + 1));
        if (key === null || value === null) return null;
        const existing = params.get(key);
        if (existing === undefined) params.set(key, value);
        else params.set(key, Array.isArray(existing) ? [...existing, value] : [existing, value]);
    }
    return Object.fromEntries(params);
}

function decodeComponent(text: string): string | null {
    try {
        return decodeURIComponent(text);
    } catch {
        return null;
    }
}

function decodeQueryComponent(text: string): string | null {
    return decodeComponent(text.replaceAll('+', '%20'));
}

/** `encodeURIComponent`, plus the five characters it leaves that the grammar doesn't allow. */
function encodeComponent(text: string): string {
    return encodeURIComponent(text).replace(
        /[!'()*]/g,
        (character) => `%${character.charCodeAt(0).toString(16).toUpperCase()}`
    );
}

function isDotSegment(segment: string): boolean {
    return segment === '.' || segment === '..';
}
