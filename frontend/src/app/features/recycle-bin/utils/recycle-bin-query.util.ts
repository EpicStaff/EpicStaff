import { RECYCLE_BIN_SOURCES, STORAGE_ITEM_KINDS } from '../constants/recycle-bin-sources.constants';
import {
    GetStorageRecycleBinEntryResponse,
    RecycleBinContentsFilter,
    RecycleBinFilterOption,
    RecycleBinListQuery,
    RecycleBinSort,
    RecycleBinSortDirection,
    RecycleBinSortField,
    RecycleBinSourceKey,
    RecycleBinTabDefinition,
} from '../models/recycle-bin.model';

/** The backend's own order: newest deletion first. */
export const DEFAULT_SORT: RecycleBinSort = { field: 'deletedAt', direction: 'desc' };

export const DEFAULT_LIST_QUERY: RecycleBinListQuery = {
    search: '',
    ordering: '-deleted_at',
    contents: null,
    itemType: null,
};

/**
 * Each sortable column's own direction, which its arrow shows: a click on a column flips that column's
 * direction and sorts by it; the other column's arrow never moves. Both start down: Deleted at newest
 * first (the backend's order), and Days left so its first click (up, fewest days first) changes the order.
 */
export const INITIAL_COLUMN_DIRECTIONS: Readonly<Record<RecycleBinSortField, RecycleBinSortDirection>> = {
    deletedAt: 'desc',
    daysLeft: 'desc',
};

/** The backend's `ordering` name of each field. */
const ORDERING_FIELD: Record<RecycleBinSortField, string> = {
    deletedAt: 'deleted_at',
    daysLeft: 'days_left',
};

/** Choices of the count column's filter (a flow's nodes, an agent's own surfaces), sent as `contents`. */
const CONTENTS_FILTER_NAMES: Record<RecycleBinContentsFilter, string> = {
    some: 'Has',
    none: 'Has none',
};

export const COUNT_FILTER_OPTIONS: readonly RecycleBinFilterOption[] = Object.entries(CONTENTS_FILTER_NAMES).map(
    ([value, name]) => ({ name, value })
);

/** The column directions after a click on `field`: only that column's arrow flips. */
export function flipColumnDirection(
    directions: Readonly<Record<RecycleBinSortField, RecycleBinSortDirection>>,
    field: RecycleBinSortField
): Record<RecycleBinSortField, RecycleBinSortDirection> {
    return { ...directions, [field]: directions[field] === 'asc' ? 'desc' : 'asc' };
}

/**
 * The server query of a tab's list. `kindFilter` is an item type on Files (on Tools it picks the source
 * instead, see shownSource); `countFilter` a COUNT_FILTER_OPTIONS value.
 */
export function toListQuery(
    search: string,
    sort: RecycleBinSort,
    kindFilter: string | null,
    countFilter: string | null
): RecycleBinListQuery {
    const prefix = sort.direction === 'desc' ? '-' : '';
    return {
        search: search.trim(),
        ordering: `${prefix}${ORDERING_FIELD[sort.field]}`,
        contents: isContentsFilter(countFilter) ? countFilter : null,
        itemType: isStorageItemType(kindFilter) ? kindFilter : null,
    };
}

/**
 * A tab with several sources (Tools) shows one at a time, and its Kind filter is a switch between them:
 * always one chosen, no "All".
 */
export function hasKindSwitch(tab: RecycleBinTabDefinition): boolean {
    return tab.sources.length > 1;
}

/** Whether the Kind filter narrows the list: a chosen kind does, unless the filter is a switch (Tools). */
export function kindFilterNarrows(kindFilter: string | null, kindSwitch: boolean): boolean {
    return kindFilter !== null && !kindSwitch;
}

/** The kind a tab starts on: its first source on a Kind switch (Tools: Python tools), otherwise all. */
export function initialKindFilter(tab: RecycleBinTabDefinition): string | null {
    return hasKindSwitch(tab) ? tab.sources[0] : null;
}

/** The bin a tab lists: the one its Kind switch picks (Tools), otherwise its only source. */
export function shownSource(tab: RecycleBinTabDefinition, kindFilter: string | null): RecycleBinSourceKey {
    return tab.sources.find((source) => source === kindFilter) ?? tab.sources[0];
}

/**
 * Options of the Kind column's filter, for the tabs that show that column (see recycleBinTabShowsKind):
 * the tool sources on Tools, file / folder on Files. Empty for every other tab.
 */
export function kindFilterOptions(tab: RecycleBinTabDefinition): RecycleBinFilterOption[] {
    if (tab.sources.includes('storage')) {
        return Object.entries(STORAGE_ITEM_KINDS).map(([value, name]) => ({ name, value }));
    }
    if (!hasKindSwitch(tab)) return [];
    return tab.sources.flatMap((source) =>
        source === 'storage' ? [] : [{ name: RECYCLE_BIN_SOURCES[source].pluralKind, value: source }]
    );
}

function isStorageItemType(value: string | null): value is GetStorageRecycleBinEntryResponse['item_type'] {
    return value !== null && Object.hasOwn(STORAGE_ITEM_KINDS, value);
}

function isContentsFilter(value: string | null): value is RecycleBinContentsFilter {
    return value !== null && Object.hasOwn(CONTENTS_FILTER_NAMES, value);
}
