import { SidebarWidthOptions } from '@shared/services';

export const COMPACT_COLUMN_WIDTH = 64;

const DESK_RAIL_MIN_WIDTH = 180;
const CONVERSATIONS_MIN_WIDTH = 280;

export const DESK_RAIL_WIDTH_KEY = 'chat-desk-rail';
export const DESK_RAIL_NARROW_WIDTH_KEY = 'chat-desk-rail-narrow';

export const DESK_RAIL_WIDTH_OPTIONS = {
    defaultWidth: 240,
    minWidth: DESK_RAIL_MIN_WIDTH,
    maxWidth: 360,
    collapse: {
        collapsedWidth: COMPACT_COLUMN_WIDTH,
        collapseThreshold: (COMPACT_COLUMN_WIDTH + DESK_RAIL_MIN_WIDTH) / 2,
    },
} as const satisfies SidebarWidthOptions;

export const DESK_RAIL_NARROW_WIDTH_OPTIONS = {
    ...DESK_RAIL_WIDTH_OPTIONS,
    defaultWidth: COMPACT_COLUMN_WIDTH,
} as const satisfies SidebarWidthOptions;

export const CONVERSATIONS_WIDTH_KEY = 'chat-conversations';

export const CONVERSATIONS_WIDTH_OPTIONS = {
    defaultWidth: 340,
    minWidth: CONVERSATIONS_MIN_WIDTH,
    maxWidth: 480,
    collapse: {
        collapsedWidth: COMPACT_COLUMN_WIDTH,
        collapseThreshold: (COMPACT_COLUMN_WIDTH + CONVERSATIONS_MIN_WIDTH) / 2,
    },
} as const satisfies SidebarWidthOptions;

export function isCompactColumn(width: number): boolean {
    return width <= COMPACT_COLUMN_WIDTH;
}
