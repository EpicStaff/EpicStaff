/** The only place a plugin page may be loaded from (the backend's token-gated asset view). */
export const PLUGIN_UI_PATH_PREFIX = '/api/plugin-ui/';

/** Longest dev URL the backend stores. */
export const PLUGIN_DEV_URL_MAX_LENGTH = 255;

/**
 * The backend's rule for a dev URL (plugin apps plan §1.3): plain `http` on `localhost` or
 * `127.0.0.1`, an optional port and path, and nothing else — no user info, query or fragment.
 */
const PLUGIN_DEV_URL_PATTERN = /^http:\/\/(localhost|127\.0\.0\.1)(:\d{1,5})?(\/[A-Za-z0-9._~/%-]*)?$/;

const PLUGIN_DEV_HOSTS: ReadonlySet<string> = new Set(['localhost', '127.0.0.1']);

/**
 * Returns the `ui-session` URL when it is safe to load in the plugin iframe, else `null`.
 *
 * It must be a same-origin path under {@link PLUGIN_UI_PATH_PREFIX}, both as written and after
 * URL normalization (so `/api/plugin-ui/../x` or a backslash trick can't escape the prefix).
 * This (or {@link toPluginDevFrameUrl} in dev mode) is the only value the host page ever loads.
 */
export function toPluginFrameUrl(url: unknown, origin: string): string | null {
    if (typeof url !== 'string' || !url.startsWith(PLUGIN_UI_PATH_PREFIX) || url.includes('\\')) return null;
    let parsed: URL;
    try {
        parsed = new URL(url, origin);
    } catch {
        return null;
    }
    if (parsed.origin !== origin || !parsed.pathname.startsWith(PLUGIN_UI_PATH_PREFIX)) return null;
    return url;
}

/**
 * Returns a dev-mode `ui-session` URL (the plugin author's own dev server) when it is safe to load
 * in the plugin iframe, else `null`: the backend's pattern, then the parsed URL must still be plain
 * `http` on a loopback host with a valid port and no user info, query or fragment.
 */
export function toPluginDevFrameUrl(url: unknown): string | null {
    if (typeof url !== 'string' || url.length > PLUGIN_DEV_URL_MAX_LENGTH || !PLUGIN_DEV_URL_PATTERN.test(url)) {
        return null;
    }
    let parsed: URL;
    try {
        parsed = new URL(url);
    } catch {
        // For example a port above 65535.
        return null;
    }
    const isPlainLoopback =
        parsed.protocol === 'http:' &&
        PLUGIN_DEV_HOSTS.has(parsed.hostname) &&
        parsed.username === '' &&
        parsed.password === '' &&
        parsed.search === '' &&
        parsed.hash === '';
    return isPlainLoopback ? url : null;
}

/** The frame URL that opens a bridge v2 page at `navPath`: the page reads its path from the fragment. */
export function withPluginNavFragment(url: string, navPath: string): string {
    const hashIndex = url.indexOf('#');
    return `${hashIndex === -1 ? url : url.slice(0, hashIndex)}#${navPath}`;
}
