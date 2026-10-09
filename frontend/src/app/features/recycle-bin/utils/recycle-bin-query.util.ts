import { RECYCLE_BIN_SOURCE_KINDS, STORAGE_ITEM_KINDS } from '../constants/recycle-bin-sources.constants';
import {
    GetStorageRecycleBinEntryResponse,
    RecycleBinFilterOption,
    RecycleBinItem,
    RecycleBinListQuery,
    RecycleBinSort,
    RecycleBinSortDirection,
    RecycleBinSortField,
    RecycleBinStorageQuery,
    RecycleBinTabDefinition,
} from '../models/recycle-bin.model';
import { newestFirst } from './recycle-bin-mappers.util';

/** The backend's own order: newest deletion first. */
export const DEFAULT_SORT: RecycleBinSort = { field: 'deletedAt', direction: 'desc' };

export const DEFAULT_STORAGE_QUERY: RecycleBinStorageQuery = { search: '', ordering: '-deleted_at', itemType: null };

/**
 * Each sortable column's own direction, which its arrow shows: a click on a column flips that column's
 * direction and sorts by it; the other column's arrow never moves. Both start down: Deleted at newest
 * first (the backend's order), and Days left so its first click (up, fewest days first) changes the order.
 */
export const INITIAL_COLUMN_DIRECTIONS: Readonly<Record<RecycleBinSortField, RecycleBinSortDirection>> = {
    deletedAt: 'desc',
    daysLeft: 'desc',
};

/** The backend's `ordering` name of each field (Files list). */
const STORAGE_ORDERING_FIELD: Record<RecycleBinSortField, string> = {
    deletedAt: 'deleted_at',
    daysLeft: 'days_left',
};

/** The column directions after a click on `field`: only that column's arrow flips. */
export function flipColumnDirection(
    directions: Readonly<Record<RecycleBinSortField, RecycleBinSortDirection>>,
    field: RecycleBinSortField
): Record<RecycleBinSortField, RecycleBinSortDirection> {
    return { ...directions, [field]: directions[field] === 'asc' ? 'desc' : 'asc' };
}

export function toStorageQuery(
    search: string,
    sort: RecycleBinSort,
    kindFilter: string | null
): RecycleBinStorageQuery {
    const prefix = sort.direction === 'desc' ? '-' : '';
    return {
        search: search.trim(),
        ordering: `${prefix}${STORAGE_ORDERING_FIELD[sort.field]}`,
        itemType: isStorageItemType(kindFilter) ? kindFilter : null,
    };
}

/**
 * Options of the Kind column's filter, for the tabs that show that column (see recycleBinTabShowsKind):
 * the tool sources on Tools, file / folder on Files. Empty for every other tab.
 */
export function kindFilterOptions(tab: RecycleBinTabDefinition): RecycleBinFilterOption[] {
    if (tab.sources.includes('storage')) {
        return Object.entries(STORAGE_ITEM_KINDS).map(([value, name]) => ({ name, value }));
    }
    if (tab.sources.length < 2) return [];
    return tab.sources.flatMap((source) =>
        source === 'storage' ? [] : [{ name: RECYCLE_BIN_SOURCE_KINDS[source], value: source }]
    );
}

interface CountRange extends RecycleBinFilterOption {
    min: number;
    max: number;
}

/** Choices of the count column's filter (a flow's nodes, an agent's own surfaces). */
const RECYCLE_BIN_COUNT_RANGES: readonly CountRange[] = [
    { name: 'Has', value: 'some', min: 1, max: Number.POSITIVE_INFINITY },
    { name: 'Has none', value: 'none', min: 0, max: 0 },
];

export const COUNT_FILTER_OPTIONS: readonly RecycleBinFilterOption[] = RECYCLE_BIN_COUNT_RANGES.map(
    ({ name, value }) => ({ name, value })
);

function isStorageItemType(value: string | null): value is GetStorageRecycleBinEntryResponse['item_type'] {
    return value !== null && value in STORAGE_ITEM_KINDS;
}

function inCountRange(count: number, rangeValue: string): boolean {
    const range = RECYCLE_BIN_COUNT_RANGES.find((candidate) => candidate.value === rangeValue);
    return range === undefined || (count >= range.min && count <= range.max);
}

/** The row's own name, or the name of something inside it (a flow's node, an agent's surface…). */
function matchesSearch(item: RecycleBinItem, term: string): boolean {
    return (
        item.displayName.toLowerCase().includes(term) ||
        item.contents.some((content) => content.name.toLowerCase().includes(term))
    );
}

/**
 * Client-side search (by the name the row shows or one of its contents), kind filter (by source, for Tools), count filter
 * (by `contentsTotal`) and sort, for the lists that aren't paged.
 */
export function filterAndSortItems(items: readonly RecycleBinItem[], query: RecycleBinListQuery): RecycleBinItem[] {
    const term = query.search.trim().toLowerCase();
    const kindFilter = query.kindFilter ?? null;
    const countFilter = query.countFilter ?? null;
    const matching = items.filter(
        (item) =>
            (!term || matchesSearch(item, term)) &&
            (kindFilter === null || item.source === kindFilter) &&
            (countFilter === null || inCountRange(item.contentsTotal, countFilter))
    );
    const sign = query.sort.direction === 'asc' ? 1 : -1;
    return matching.sort(
        (first, second) => sign * compareBy(query.sort.field, first, second) || newestFirst(first, second)
    );
}

function compareBy(field: RecycleBinSortField, first: RecycleBinItem, second: RecycleBinItem): number {
    switch (field) {
        case 'deletedAt':
            return first.deletedAt.getTime() - second.deletedAt.getTime();
        case 'daysLeft':
            // Less time left means deleted earlier. Not `daysLeft`: it's whole days, and the cells show hours.
            return first.deletedAt.getTime() - second.deletedAt.getTime();
    }
}
