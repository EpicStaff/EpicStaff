import { UrlMatchResult, UrlSegment } from '@angular/router';

/** First segment of every plugin page address: `/plugins/<id>/…`. */
export const PLUGIN_PAGE_ROUTE_SEGMENT = 'plugins';

/** Index of the plugin id among the consumed segments. */
export const PLUGIN_PAGE_ID_SEGMENT_INDEX = 1;

/** Segments of a plugin page address before the page's own path: `plugins` and the id. */
export const PLUGIN_PAGE_ROUTE_PREFIX_LENGTH = 2;

/**
 * Matches `plugins/<id>` and everything below it (`plugins/<id>/conversations/42`). The rest of the
 * address is the plugin page's own path, so a deep link opens the same host page, and moving
 * between two paths of one plugin reuses it. The host page reads the id and the page path from
 * the consumed segments; `id` is also the route param.
 *
 * An address with matrix params (`;name=value`) on any segment matches nothing: the router merges
 * the last consumed segment's matrix params into the route params, so `/plugins/7/x;id=9` would
 * otherwise open plugin 9 at an address that names plugin 7. A plugin path has no matrix params
 * (a `;` the page puts in a segment is `%`-encoded).
 */
export function pluginPageMatcher(segments: UrlSegment[]): UrlMatchResult | null {
    if (segments.length < PLUGIN_PAGE_ROUTE_PREFIX_LENGTH || segments[0].path !== PLUGIN_PAGE_ROUTE_SEGMENT) {
        return null;
    }
    if (segments.some((segment) => Object.keys(segment.parameters).length > 0)) return null;
    return { consumed: segments, posParams: { id: segments[PLUGIN_PAGE_ID_SEGMENT_INDEX] } };
}
