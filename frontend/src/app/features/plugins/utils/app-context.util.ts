import { DefaultUrlSerializer, PRIMARY_OUTLET, UrlSegment } from '@angular/router';

import {
    PLUGIN_PAGE_IDENTIFIER_SEGMENT_INDEX,
    PLUGIN_PAGE_ROUTE_PREFIX_LENGTH,
    pluginPageMatcher,
} from '../pages/plugin-host-page/plugin-page.matcher';

/** One of EpicStaff's own pages: the sidebar shows EpicStaff's navigation. */
export interface EpicStaffContext {
    readonly kind: 'epicstaff';
}

/** A plugin page, `/plugins/<identifier>/…`: the sidebar shows that app's navigation. */
export interface AppContext {
    readonly kind: 'app';
    readonly identifier: string;
    /** The decoded path segments below `/plugins/<identifier>`; `[]` on the app's root page. */
    readonly pageSegments: readonly string[];
}

/** What the address shows, as far as the sidebar is concerned. */
export type NavigationContext = EpicStaffContext | AppContext;

export const EPICSTAFF_CONTEXT: EpicStaffContext = { kind: 'epicstaff' };

/** The manifest's cap on an app menu path; a longer one is not taken from the server either. */
export const MAX_MENU_PATH_LENGTH = 256;

/** The manifest's rule for an app menu path: `/`, or `/`-separated segments of unreserved characters. */
const MENU_PATH_PATTERN = /^\/(?:[A-Za-z0-9._~-]+(?:\/[A-Za-z0-9._~-]+)*)?$/;

const urlSerializer = new DefaultUrlSerializer();

/**
 * The context of a router URL. A plugin page exactly when the plugin page route would match it
 * ({@link pluginPageMatcher}): `/plugins` alone, or an address with matrix params, is not one. The query and the
 * fragment don't count.
 */
export function navigationContextOf(url: string): NavigationContext {
    let segments: UrlSegment[];
    try {
        segments = urlSerializer.parse(url).root.children[PRIMARY_OUTLET]?.segments ?? [];
    } catch {
        // A malformed `%` escape: the router would not show a plugin page for it either.
        return EPICSTAFF_CONTEXT;
    }
    if (pluginPageMatcher(segments) === null) return EPICSTAFF_CONTEXT;
    return {
        kind: 'app',
        identifier: segments[PLUGIN_PAGE_IDENTIFIER_SEGMENT_INDEX].path,
        pageSegments: segments.slice(PLUGIN_PAGE_ROUTE_PREFIX_LENGTH).map((segment) => segment.path),
    };
}

/**
 * The segments of an app menu path (`/` has none), or `null` when it breaks the manifest's rule. The server checked
 * it already; an item that fails here is dropped all the same.
 */
export function menuPathSegments(path: unknown): string[] | null {
    if (typeof path !== 'string' || path.length > MAX_MENU_PATH_LENGTH || !MENU_PATH_PATTERN.test(path)) return null;
    const segments = path === '/' ? [] : path.slice(1).split('/');
    return segments.some((segment) => segment === '.' || segment === '..') ? null : segments;
}

/**
 * The menu item a page belongs to: the one whose path is the longest segment-wise prefix of the page's path. The root
 * item (`/`) belongs to the app's root page only, so it does not light up on every page.
 */
export function activeMenuItem<Item extends { readonly path: string }>(
    items: readonly Item[],
    pageSegments: readonly string[]
): Item | null {
    let active: Item | null = null;
    let activeLength = -1;
    for (const item of items) {
        const segments = menuPathSegments(item.path);
        if (segments === null || !isPageOf(segments, pageSegments)) continue;
        if (segments.length > activeLength) {
            active = item;
            activeLength = segments.length;
        }
    }
    return active;
}

function isPageOf(menuSegments: readonly string[], pageSegments: readonly string[]): boolean {
    if (menuSegments.length === 0) return pageSegments.length === 0;
    return (
        menuSegments.length <= pageSegments.length &&
        menuSegments.every((segment, index) => segment === pageSegments[index])
    );
}
