import { RECYCLE_BIN_TAB_BY_KEY } from '../constants/recycle-bin-tabs.constants';
import { RecycleBinItem } from '../models/recycle-bin.model';
import {
    DEFAULT_SORT,
    filterAndSortItems,
    flipColumnDirection,
    INITIAL_COLUMN_DIRECTIONS,
    kindFilterOptions,
    toStorageQuery,
} from './recycle-bin-query.util';

function binItem(id: number, displayName: string, deletedAt: string, daysLeft: number): RecycleBinItem {
    return {
        key: `flow-${id}`,
        id,
        source: 'flow',
        name: displayName,
        displayName,
        kind: 'Flow',
        deletedAt: new Date(deletedAt),
        daysLeft,
        details: [],
        contents: [],
        contentsTotal: 0,
    };
}

const ITEMS = [
    binItem(1, 'beta', '2026-10-02T10:00:00Z', 6),
    binItem(2, 'Alpha', '2026-10-03T10:00:00Z', 7),
    binItem(3, 'gamma', '2026-10-01T10:00:00Z', 5),
];

function names(items: RecycleBinItem[]): string[] {
    return items.map((item) => item.displayName);
}

describe('recycle bin query', () => {
    it('sorts newest first by default', () => {
        expect(names(filterAndSortItems(ITEMS, { search: '', sort: DEFAULT_SORT }))).toEqual([
            'Alpha',
            'beta',
            'gamma',
        ]);
    });

    it('sorts by days left', () => {
        expect(names(filterAndSortItems(ITEMS, { search: '', sort: { field: 'daysLeft', direction: 'asc' } }))).toEqual(
            ['gamma', 'beta', 'Alpha']
        );
    });

    it('orders Days left by the hour within a day, not only by whole days', () => {
        // Both have 6 whole days left; the one deleted earlier has less time left.
        const earlier = binItem(1, 'earlier', '2026-10-02T08:00:00Z', 6);
        const later = binItem(2, 'later', '2026-10-02T10:00:00Z', 6);
        const sort = { field: 'daysLeft', direction: 'asc' } as const;

        expect(names(filterAndSortItems([later, earlier], { search: '', sort }))).toEqual(['earlier', 'later']);
    });

    it('finds a row by a name inside it too (a node, a surface)', () => {
        const flow = {
            ...binItem(9, 'Nightly', '2026-10-01T10:00:00Z', 5),
            contents: [{ name: 'Send Invoice', nodeType: 'task' }],
        };
        expect(names(filterAndSortItems([...ITEMS, flow], { search: 'invoice', sort: DEFAULT_SORT }))).toEqual([
            'Nightly',
        ]);
    });

    it('searches the shown name, case-insensitively', () => {
        expect(names(filterAndSortItems(ITEMS, { search: '  ALP ', sort: DEFAULT_SORT }))).toEqual(['Alpha']);
    });

    it('flips only the clicked column, every click, and leaves the other one as it was', () => {
        const afterDaysLeft = flipColumnDirection(INITIAL_COLUMN_DIRECTIONS, 'daysLeft');
        expect(afterDaysLeft).toEqual({ deletedAt: 'desc', daysLeft: 'asc' });
        expect(flipColumnDirection(afterDaysLeft, 'daysLeft')).toEqual({ deletedAt: 'desc', daysLeft: 'desc' });
        expect(flipColumnDirection(afterDaysLeft, 'deletedAt')).toEqual({ deletedAt: 'asc', daysLeft: 'asc' });
    });

    it('starts on newest first, where the first click on Days left reorders the list', () => {
        expect(INITIAL_COLUMN_DIRECTIONS[DEFAULT_SORT.field]).toBe(DEFAULT_SORT.direction);
        expect(flipColumnDirection(INITIAL_COLUMN_DIRECTIONS, 'daysLeft').daysLeft).toBe('asc');
    });

    it('builds the Files ordering the backend takes', () => {
        expect(toStorageQuery(' rep ', { field: 'deletedAt', direction: 'desc' }, null)).toEqual({
            search: 'rep',
            ordering: '-deleted_at',
            itemType: null,
        });
        expect(toStorageQuery('', { field: 'daysLeft', direction: 'asc' }, 'folder')).toEqual({
            search: '',
            ordering: 'days_left',
            itemType: 'folder',
        });
        expect(toStorageQuery('', { field: 'deletedAt', direction: 'asc' }, null).ordering).toBe('deleted_at');
    });

    it('offers tool kinds on Tools, item types on Files, and nothing elsewhere', () => {
        expect(kindFilterOptions(RECYCLE_BIN_TAB_BY_KEY.tools)).toEqual([
            { name: 'Python tool', value: 'python_tool' },
            { name: 'MCP tool', value: 'mcp_tool' },
        ]);
        expect(kindFilterOptions(RECYCLE_BIN_TAB_BY_KEY.files)).toEqual([
            { name: 'File', value: 'file' },
            { name: 'Folder', value: 'folder' },
        ]);
        expect(kindFilterOptions(RECYCLE_BIN_TAB_BY_KEY.flows)).toEqual([]);
    });

    it('filters by source on the client', () => {
        const mixed = [ITEMS[0], { ...ITEMS[1], key: 'mcp_tool-2', source: 'mcp_tool' as const }];
        expect(names(filterAndSortItems(mixed, { search: '', sort: DEFAULT_SORT, kindFilter: 'mcp_tool' }))).toEqual([
            'Alpha',
        ]);
    });

    it.each([
        ['none', ['zero']],
        ['some', ['one', 'five', 'six', 'ten', 'eleven']],
    ])('keeps the rows whose count matches %s', (range, expected) => {
        const counts: [string, number][] = [
            ['zero', 0],
            ['one', 1],
            ['five', 5],
            ['six', 6],
            ['ten', 10],
            ['eleven', 11],
        ];
        const counted = counts.map(([name, total], index) => ({
            ...binItem(index + 1, name, '2026-10-01T10:00:00Z', 5),
            contentsTotal: total,
        }));
        const sort = { field: 'deletedAt', direction: 'asc' } as const;
        expect(names(filterAndSortItems(counted, { search: '', sort, countFilter: range })).sort()).toEqual(
            [...expected].sort()
        );
    });
});
