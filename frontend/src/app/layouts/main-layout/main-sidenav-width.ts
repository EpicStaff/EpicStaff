import { SidebarWidthOptions } from '@shared/services';

/** Storage key of the app's left navigation sidebar width (persisted by SidebarWidthService). */
export const MAIN_SIDENAV_WIDTH_KEY = 'main-sidenav';

/** Icons-only width; also the width for users who never resized the sidebar. */
export const MAIN_SIDENAV_COLLAPSED_WIDTH = 60;

/**
 * Collapsed, or expanded between 200 and 320px. The minimum fits the widest nav row, "Conversations" (~161px),
 * without an ellipsis. The "EpicStaff" wordmark is the only text that would not fit at the minimum: it shrinks
 * with the sidebar instead (see the sidenav styles).
 * Dragging below 130px (halfway between the two states) collapses the sidebar, at or above it expands it.
 */
export const MAIN_SIDENAV_WIDTH_OPTIONS = {
    defaultWidth: MAIN_SIDENAV_COLLAPSED_WIDTH,
    minWidth: 200,
    maxWidth: 320,
    collapse: {
        collapsedWidth: MAIN_SIDENAV_COLLAPSED_WIDTH,
        collapseThreshold: 130,
    },
} as const satisfies SidebarWidthOptions;

/** Any width above the collapsed one is expanded — derived from the width, never stored separately. */
export function isMainSidenavExpanded(width: number): boolean {
    return width > MAIN_SIDENAV_COLLAPSED_WIDTH;
}
