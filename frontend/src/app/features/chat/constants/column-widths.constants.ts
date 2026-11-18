import { SidebarWidthOptions } from '@shared/services';

export const COMPACT_COLUMN_WIDTH = 64;

/** 40px desk avatars, 10px either side of them and the rail's 1px divider. */
const DESK_RAIL_COMPACT_WIDTH = 61;
const DESK_RAIL_MIN_WIDTH = 180;
/**
 * The designer's minimum: the toolbar's rows (the switch, then the search with Mine) at 318px, with the toolbar's 12px
 * padding either side and the column's 1px divider (see the default). The column shrinks to it with the screen too.
 */
const CONVERSATIONS_MIN_WIDTH = 343;

export const DESK_RAIL_WIDTH_KEY = 'chat-desk-rail';
export const DESK_RAIL_NARROW_WIDTH_KEY = 'chat-desk-rail-narrow';

export const DESK_RAIL_WIDTH_OPTIONS = {
    defaultWidth: 240,
    minWidth: DESK_RAIL_MIN_WIDTH,
    maxWidth: 360,
    collapse: {
        collapsedWidth: DESK_RAIL_COMPACT_WIDTH,
        collapseThreshold: (DESK_RAIL_COMPACT_WIDTH + DESK_RAIL_MIN_WIDTH) / 2,
    },
} as const satisfies SidebarWidthOptions;

export const DESK_RAIL_NARROW_WIDTH_OPTIONS = {
    ...DESK_RAIL_WIDTH_OPTIONS,
    defaultWidth: DESK_RAIL_COMPACT_WIDTH,
} as const satisfies SidebarWidthOptions;

export const CONVERSATIONS_WIDTH_KEY = 'chat-conversations';

/**
 * The column before the user resizes it. The Inbox / Bot Testing switch fills the toolbar's first row, so it is the
 * column less the toolbar's 12px padding either side and the column's 1px divider: 402px here.
 */
const CONVERSATIONS_DEFAULT_WIDTH = 427;

export const CONVERSATIONS_WIDTH_OPTIONS = {
    defaultWidth: CONVERSATIONS_DEFAULT_WIDTH,
    minWidth: CONVERSATIONS_MIN_WIDTH,
    maxWidth: 480,
} as const satisfies SidebarWidthOptions;

export function isCompactColumn(width: number): boolean {
    return width <= COMPACT_COLUMN_WIDTH;
}
