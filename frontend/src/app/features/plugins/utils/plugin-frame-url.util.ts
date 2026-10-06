/** The only place a plugin page may be loaded from (the backend's token-gated asset view). */
export const PLUGIN_UI_PATH_PREFIX = '/api/plugin-ui/';

/**
 * Returns the `ui-session` URL when it is safe to trust as the iframe's resource URL, else `null`.
 *
 * It must be a same-origin path under {@link PLUGIN_UI_PATH_PREFIX}, both as written and after
 * URL normalization (so `/api/plugin-ui/../x` or a backslash trick can't escape the prefix).
 * This is the only value the host page ever passes to `bypassSecurityTrustResourceUrl`.
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
