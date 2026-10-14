import { RECYCLE_BIN_TAB_BY_KEY } from '../constants/recycle-bin-tabs.constants';
import {
    COUNT_FILTER_OPTIONS,
    DEFAULT_SORT,
    flipColumnDirection,
    hasKindSwitch,
    INITIAL_COLUMN_DIRECTIONS,
    initialKindFilter,
    kindFilterNarrows,
    kindFilterOptions,
    shownSource,
    toListQuery,
} from './recycle-bin-query.util';

describe('recycle bin query', () => {
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

    it('builds the ordering the backend takes', () => {
        expect(toListQuery(' rep ', { field: 'deletedAt', direction: 'desc' }, null, null)).toEqual({
            search: 'rep',
            ordering: '-deleted_at',
            contents: null,
            itemType: null,
        });
        expect(toListQuery('', { field: 'daysLeft', direction: 'asc' }, null, null).ordering).toBe('days_left');
        expect(toListQuery('', { field: 'daysLeft', direction: 'desc' }, null, null).ordering).toBe('-days_left');
        expect(toListQuery('', { field: 'deletedAt', direction: 'asc' }, null, null).ordering).toBe('deleted_at');
    });

    it('sends an item type and a count filter only when they are ones the backend knows', () => {
        expect(toListQuery('', DEFAULT_SORT, 'folder', 'some')).toMatchObject({ itemType: 'folder', contents: 'some' });
        expect(toListQuery('', DEFAULT_SORT, null, 'none').contents).toBe('none');
        // Tools' Kind switch holds a source key: that picks the bin, it is no item type.
        expect(toListQuery('', DEFAULT_SORT, 'mcp_tool', null).itemType).toBeNull();
        expect(toListQuery('', DEFAULT_SORT, 'toString', 'toString')).toMatchObject({
            itemType: null,
            contents: null,
        });
    });

    it('offers has / has none on the count column', () => {
        expect(COUNT_FILTER_OPTIONS).toEqual([
            { name: 'Has', value: 'some' },
            { name: 'Has none', value: 'none' },
        ]);
    });

    it('offers the tool bins on Tools, item types on Files, and nothing elsewhere', () => {
        expect(kindFilterOptions(RECYCLE_BIN_TAB_BY_KEY.tools)).toEqual([
            { name: 'Python tools', value: 'python_tool' },
            { name: 'MCP tools', value: 'mcp_tool' },
        ]);
        expect(kindFilterOptions(RECYCLE_BIN_TAB_BY_KEY.files)).toEqual([
            { name: 'File', value: 'file' },
            { name: 'Folder', value: 'folder' },
        ]);
        expect(kindFilterOptions(RECYCLE_BIN_TAB_BY_KEY.flows)).toEqual([]);
    });

    it('makes the Kind filter a switch only on Tools, starting on Python tools', () => {
        expect(hasKindSwitch(RECYCLE_BIN_TAB_BY_KEY.tools)).toBe(true);
        expect(hasKindSwitch(RECYCLE_BIN_TAB_BY_KEY.files)).toBe(false);
        expect(initialKindFilter(RECYCLE_BIN_TAB_BY_KEY.tools)).toBe('python_tool');
        expect(initialKindFilter(RECYCLE_BIN_TAB_BY_KEY.files)).toBeNull();
    });

    it('counts a chosen kind as narrowing the list only when the Kind filter is no switch', () => {
        expect(kindFilterNarrows('folder', false)).toBe(true);
        expect(kindFilterNarrows(null, false)).toBe(false);
        expect(kindFilterNarrows('mcp_tool', true)).toBe(false);
    });

    it('lists the bin the Kind switch picks on Tools, and the only bin elsewhere', () => {
        expect(shownSource(RECYCLE_BIN_TAB_BY_KEY.tools, 'mcp_tool')).toBe('mcp_tool');
        expect(shownSource(RECYCLE_BIN_TAB_BY_KEY.tools, 'python_tool')).toBe('python_tool');
        expect(shownSource(RECYCLE_BIN_TAB_BY_KEY.files, 'folder')).toBe('storage');
        expect(shownSource(RECYCLE_BIN_TAB_BY_KEY.flows, null)).toBe('flow');
    });
});
