import { UrlMatchResult, UrlSegment } from '@angular/router';

/** First segment of every plugin page address: `/plugins/<identifier>/…`. */
export const PLUGIN_PAGE_ROUTE_SEGMENT = 'plugins';

/** Index of the plugin identifier among the consumed segments. */
export const PLUGIN_PAGE_IDENTIFIER_SEGMENT_INDEX = 1;

/** Segments of a plugin page address before the page's own path: `plugins` and the identifier. */
export const PLUGIN_PAGE_ROUTE_PREFIX_LENGTH = 2;

/** The route param that holds the plugin identifier. */
export const PLUGIN_PAGE_IDENTIFIER_PARAM = 'identifier';

/**
 * Matches `plugins/<identifier>` and everything below it (`plugins/weather/forecast/berlin`). The rest of the address
 * is the plugin page's own path, so a deep link opens the same host page, and moving between two paths of one plugin
 * reuses it. The host page reads the identifier and the page path from the consumed segments; `identifier` is also
 * the route param.
 *
 * An address with matrix params (`;name=value`) on any segment matches nothing: the router merges the last consumed
 * segment's matrix params into the route params, so `/plugins/weather/x;identifier=chat` would otherwise open `chat`
 * at an address that names `weather`. A plugin path has no matrix params (a `;` the page puts in a segment is
 * `%`-encoded).
 */
export function pluginPageMatcher(segments: UrlSegment[]): UrlMatchResult | null {
    if (segments.length < PLUGIN_PAGE_ROUTE_PREFIX_LENGTH || segments[0].path !== PLUGIN_PAGE_ROUTE_SEGMENT) {
        return null;
    }
    if (segments.some((segment) => Object.keys(segment.parameters).length > 0)) return null;
    return {
        consumed: segments,
        posParams: { [PLUGIN_PAGE_IDENTIFIER_PARAM]: segments[PLUGIN_PAGE_IDENTIFIER_SEGMENT_INDEX] },
    };
}
