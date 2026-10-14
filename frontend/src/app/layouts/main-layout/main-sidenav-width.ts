import { SidebarWidthOptions } from '@shared/services';

/** Storage key of the app's left navigation sidebar width (persisted by SidebarWidthService). */
export const MAIN_SIDENAV_WIDTH_KEY = 'main-sidenav';

/** Icons-only width; also the width for users who never resized the sidebar. */
export const MAIN_SIDENAV_COLLAPSED_WIDTH = 60;

/**
 * Collapsed, or expanded between 210 and 320px. The logo row is the widest fixed content: 10px inset + 40px
 * logo mark + 8px gap + ~85px "EpicStaff" (text-h4) + 8px gap + 28px close button + 10px inset + 1px border
 * = ~190px, plus ~20px slack for font rendering. Dragging below 135px (halfway between the two states)
 * collapses the sidebar, at or above it expands it.
 */
export const MAIN_SIDENAV_WIDTH_OPTIONS = {
    defaultWidth: MAIN_SIDENAV_COLLAPSED_WIDTH,
    minWidth: 210,
    maxWidth: 320,
    collapse: {
        collapsedWidth: MAIN_SIDENAV_COLLAPSED_WIDTH,
        collapseThreshold: 135,
    },
} as const satisfies SidebarWidthOptions;

/** Any width above the collapsed one is expanded — derived from the width, never stored separately. */
export function isMainSidenavExpanded(width: number): boolean {
    return width > MAIN_SIDENAV_COLLAPSED_WIDTH;
}
