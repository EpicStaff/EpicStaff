import { PLUGIN_ORG_HINT_PARAMETER } from '../constants/plugin-frame-protocol.constants';
import { navPathFromRoute, parseNavPath, PLUGIN_ROOT_NAV_PATH } from './plugin-nav-path.util';

/** The manifest's rule for a plugin identifier; it is also the first label of the plugin's host. */
export const PLUGIN_IDENTIFIER_PATTERN = /^[a-z][a-z0-9-]{0,30}[a-z0-9]$/;

/** Plain http is allowed only for local development hosts. */
const LOCAL_DEVELOPMENT_HOST_SUFFIX = '.localhost';

export interface PluginFrameUrlRequest {
    /** `frame_origin` as the backend sent it. */
    frameOrigin: unknown;
    identifier: string;
    /** The plugin page's path below `/plugins/<identifier>`, as EpicStaff's address shows it. */
    navPath: string;
    /** The active organization, passed to the page as the `es_org` hint. */
    orgId: number;
    /** EpicStaff's own origin. */
    hostOrigin: string;
}

/**
 * The affixes `PLUGINS_HOST_TEMPLATE` may put around the identifier in a host's first label (the backend's own rule):
 * lower-case letters, digits and hyphens, never a hyphen at the label's outer edge.
 */
const HOST_LABEL_PREFIX_PATTERN = '(?:[a-z0-9][a-z0-9-]*)?';
const HOST_LABEL_SUFFIX_PATTERN = '(?:[a-z0-9-]*[a-z0-9])?';

/** `PLUGINS_HOST_TEMPLATE` puts at least two labels after the plugin's own (`example.com`). */
const MIN_PARENT_DOMAIN_LABELS = 2;

/**
 * Returns the backend's `frame_origin` for a plugin when it is safe to frame, else `null`.
 *
 * What it guarantees: https, or http only on a `*.localhost` host; an optional port; no credentials, path, query or
 * fragment (the string is exactly an origin); never EpicStaff's own origin (a same-origin frame with `allow-scripts
 * allow-same-origin` could lift its own sandbox); at least two non-empty labels after the first; and the identifier
 * inside the first label, with nothing around it but `[a-z0-9-]` affixes that neither start nor end with a hyphen.
 *
 * It is a containment check, not the host template: `PLUGINS_HOST_TEMPLATE` is not known here, so it accepts
 * `weather.plugins.example.com`, `weather-app.example.com` and `app-weather.example.com` alike, and also
 * `chatwoot.example.com` for `chat`. Which host a plugin really has is the backend's to decide: it builds
 * `frame_origin` from its settings and proves the host is served by this EpicStaff before it calls the plugin ready.
 */
export function toPluginFrameOrigin(frameOrigin: unknown, identifier: string, hostOrigin: string): string | null {
    if (typeof frameOrigin !== 'string' || !PLUGIN_IDENTIFIER_PATTERN.test(identifier)) return null;
    let parsed: URL;
    try {
        parsed = new URL(frameOrigin);
    } catch {
        return null;
    }
    if (parsed.origin !== frameOrigin || parsed.origin === hostOrigin) return null;
    const isSecure = parsed.protocol === 'https:';
    const isLocalDevelopment = parsed.protocol === 'http:' && parsed.hostname.endsWith(LOCAL_DEVELOPMENT_HOST_SUFFIX);
    if (!isSecure && !isLocalDevelopment) return null;
    const [firstLabel, ...parentLabels] = parsed.hostname.split('.');
    const hasParentDomain =
        parentLabels.length >= MIN_PARENT_DOMAIN_LABELS && parentLabels.every((label) => label !== '');
    return hasParentDomain && pluginHostLabelPattern(identifier).test(firstLabel) ? frameOrigin : null;
}

/**
 * The whole first label of a plugin's host: the identifier, with the template's prefix and suffix around it. The
 * identifier goes in unescaped: the caller checked it against `PLUGIN_IDENTIFIER_PATTERN`, which allows no character
 * a regular expression treats specially.
 */
function pluginHostLabelPattern(identifier: string): RegExp {
    return new RegExp(`^${HOST_LABEL_PREFIX_PATTERN}${identifier}${HOST_LABEL_SUFFIX_PATTERN}$`);
}

/**
 * The address the host page frames: the plugin origin, the page's navigation path (canonical; `es_org` is reserved,
 * so the page's own query loses it) and `es_org=<org id>` appended with `?` or `&`. `null` when the origin is not safe
 * ({@link toPluginFrameOrigin}), the org id is not a positive integer, or the result would leave the origin.
 *
 * The URL carries no credentials: the page learns who is signed in only through its own login.
 */
export function toPluginFrameUrl(request: PluginFrameUrlRequest): string | null {
    const origin = toPluginFrameOrigin(request.frameOrigin, request.identifier, request.hostOrigin);
    if (origin === null || !Number.isSafeInteger(request.orgId) || request.orgId <= 0) return null;

    const target = parseNavPath(request.navPath);
    const queryParams = Object.fromEntries(
        Object.entries(target?.queryParams ?? {}).filter(([key]) => key !== PLUGIN_ORG_HINT_PARAMETER)
    );
    const path = target ? navPathFromRoute(target.segments, queryParams) : PLUGIN_ROOT_NAV_PATH;
    const separator = path.includes('?') ? '&' : '?';
    const url = `${origin}${path}${separator}${PLUGIN_ORG_HINT_PARAMETER}=${request.orgId}`;
    try {
        return new URL(url).origin === origin ? url : null;
    } catch {
        return null;
    }
}
