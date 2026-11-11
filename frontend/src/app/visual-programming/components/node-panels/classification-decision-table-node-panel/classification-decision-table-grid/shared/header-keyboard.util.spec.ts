import {
    Column,
    ColumnGroup,
    GridApi,
    HeaderPosition,
    NavigateToNextHeaderParams,
    TabToNextHeaderParams,
} from 'ag-grid-community';

import {
    badgeClosingHeader,
    HeaderBadgeBoundary,
    HeaderTabStop,
    headerTabTarget,
    navigatePastActionlessHeaders,
    stopPastActionlessHeader,
    tabPastActionlessHeaders,
} from './header-keyboard.util';

/**
 * The header keyboard rules against a minimal stand-in for ag-grid's column model:
 * only the calls the util makes (displayed columns, their neighbours, the group
 * chain above a column, the row count).
 */

interface FakeGroup {
    getProvidedColumnGroup(): { getLevel(): number };
    getDisplayedLeafColumns(): FakeColumn[];
    getParent(): FakeGroup | null;
    isPadding(): boolean;
}

interface FakeColumn {
    getColId(): string;
    getParent(): FakeGroup | null;
    isSpanHeaderHeight(): boolean;
}

type ColumnLayout = string | { readonly group: string; readonly children: readonly string[] };

interface FakeGrid {
    readonly api: GridApi;
    column(colId: string): Column;
    /** A named group's cell on the group row. */
    group(id: string): ColumnGroup;
}

/**
 * A grid with the given columns, laid out the way ag-grid does once any group exists:
 * a named group over its children on the group row, and an unrendered padding group
 * over each lone column, whose own cell spans both header rows (ag-grid's default
 * `spanHeaderHeight`). Without groups there is a single header row.
 */
function fakeGrid(layout: readonly ColumnLayout[], options: { rowCount?: number } = {}): FakeGrid {
    const grouped = layout.some((entry) => typeof entry !== 'string');
    const columns: FakeColumn[] = [];
    const groups = new Map<string, FakeGroup>();

    for (const entry of layout) {
        const isNamedGroup = typeof entry !== 'string';
        const colIds = isNamedGroup ? entry.children : [entry];
        const members: FakeColumn[] = [];
        const group: FakeGroup | null = grouped
            ? {
                  getProvidedColumnGroup: () => ({ getLevel: () => 0 }),
                  getDisplayedLeafColumns: () => members,
                  getParent: () => null,
                  isPadding: () => !isNamedGroup,
              }
            : null;
        if (group && isNamedGroup) groups.set(entry.group, group);
        for (const colId of colIds) {
            const column: FakeColumn = {
                getColId: () => colId,
                getParent: () => group,
                isSpanHeaderHeight: () => true,
            };
            members.push(column);
            columns.push(column);
        }
    }

    const neighbour = (column: FakeColumn, offset: number): FakeColumn | null =>
        columns[columns.indexOf(column) + offset] ?? null;
    const api = {
        getAllDisplayedColumns: () => columns,
        getDisplayedColBefore: (column: FakeColumn) => neighbour(column, -1),
        getDisplayedColAfter: (column: FakeColumn) => neighbour(column, 1),
        getDisplayedRowCount: () => options.rowCount ?? 1,
    };

    return {
        api: api as unknown as GridApi,
        column: (colId) => {
            const found = columns.find((column) => column.getColId() === colId);
            if (!found) throw new Error(`no column ${colId}`);
            return found as unknown as Column;
        },
        group: (id) => {
            const found = groups.get(id);
            if (!found) throw new Error(`no group ${id}`);
            return found as unknown as ColumnGroup;
        },
    };
}

/** The classification table's shape: the actionless selection column first, then a params group. */
const LAYOUT: readonly ColumnLayout[] = [
    'selection',
    'dock_visible',
    'group_name',
    { group: 'params', children: ['field_a', 'field_b'] },
    'expression',
];

const GROUP_ROW = 0;
const LEAF_ROW = 1;
const HEADER_ROW_COUNT = 2;

const grid = fakeGrid(LAYOUT);
const leafCell = (colId: string): HeaderPosition => ({ headerRowIndex: LEAF_ROW, column: grid.column(colId) });
const paramsCell: HeaderPosition = { headerRowIndex: GROUP_ROW, column: grid.group('params') };

describe('tabPastActionlessHeaders', () => {
    function tab(from: HeaderPosition, backwards: boolean, on: FakeGrid = grid): HeaderPosition | boolean {
        return tabPastActionlessHeaders({
            api: on.api,
            backwards,
            previousHeaderPosition: from,
            nextHeaderPosition: null,
            headerRowCount: HEADER_ROW_COUNT,
        } as unknown as TabToNextHeaderParams);
    }

    it.each([
        ['a lone column to the next one', leafCell('dock_visible'), false, leafCell('group_name')],
        ['a lone column to the group cell over the next columns', leafCell('group_name'), false, paramsCell],
        ['a group cell to its first column', paramsCell, false, leafCell('field_a')],
        ['the last column of a group to the column after it', leafCell('field_b'), false, leafCell('expression')],
        ['the first column of a group back to the group cell', leafCell('field_a'), true, paramsCell],
        ['a group cell back to the column before it', paramsCell, true, leafCell('group_name')],
    ])('goes in reading order from %s', (_case, from, backwards, expected) => {
        expect(tab(from, backwards)).toEqual(expected);
    });

    it('goes from the last header into the body, at the first displayed column', () => {
        // The selection header is skipped, but its body cell is where the body starts.
        expect(tab(leafCell('expression'), false)).toEqual({ headerRowIndex: -1, column: grid.column('selection') });
    });

    it('leaves the grid on Shift+Tab from the first header, past the selection header', () => {
        expect(tab(leafCell('dock_visible'), true)).toBe(false);
    });

    it('goes into the body from the end of a single header row', () => {
        const flat = fakeGrid(['selection', 'group_name', 'expression']);

        expect(tab({ headerRowIndex: 0, column: flat.column('expression') }, false, flat)).toEqual({
            headerRowIndex: -1,
            column: flat.column('selection'),
        });
    });
});

describe('navigatePastActionlessHeaders', () => {
    function arrow(from: HeaderPosition, key: 'ArrowLeft' | 'ArrowRight'): HeaderPosition | null {
        return navigatePastActionlessHeaders({
            api: grid.api,
            key,
            previousHeaderPosition: from,
            nextHeaderPosition: null,
            headerRowCount: HEADER_ROW_COUNT,
        } as unknown as NavigateToNextHeaderParams);
    }

    it('goes right from a group cell to the next lone column, whose cell spans the group row', () => {
        expect(arrow(paramsCell, 'ArrowRight')).toEqual(leafCell('expression'));
    });

    it('goes left from a group cell to the lone column before it', () => {
        expect(arrow(paramsCell, 'ArrowLeft')).toEqual(leafCell('group_name'));
    });

    it('stays put at the first header rather than stop on the selection header', () => {
        expect(arrow(leafCell('dock_visible'), 'ArrowLeft')).toBeNull();
    });
});

describe('headerTabTarget', () => {
    /**
     * Badges: one for a column hidden between the selection column and Enable, one
     * between Condition Name and the params group, one past the last column.
     */
    const BADGES: readonly HeaderBadgeBoundary[] = [
        { prevColId: 'selection', nextColId: 'dock_visible' },
        { prevColId: 'group_name', nextColId: 'field_a' },
        { prevColId: 'expression', nextColId: null },
    ];
    const BY_SELECTION = 0;
    const BEFORE_PARAMS = 1;
    const LAST = 2;

    const badge = (badgeIndex: number): HeaderTabStop => ({ kind: 'badge', badgeIndex });
    const header = (position: HeaderPosition): HeaderTabStop => ({ kind: 'header', position });

    it.each([
        ['a header to the badge right after it', header(leafCell('group_name')), badge(BEFORE_PARAMS)],
        ['a badge to the group cell starting at its boundary', badge(BEFORE_PARAMS), header(paramsCell)],
        ['a header to the next header', header(leafCell('field_a')), header(leafCell('field_b'))],
        ['the last header to a badge past the last column', header(leafCell('expression')), badge(LAST)],
        [
            'a badge beside the skipped selection column to the first header',
            badge(BY_SELECTION),
            header(leafCell('dock_visible')),
        ],
    ])('Tab goes from %s', (_case, from, expected) => {
        expect(headerTabTarget(grid.api, BADGES, from, false)).toEqual(expected);
    });

    it.each([
        ['a group cell to the badge before it', header(paramsCell), badge(BEFORE_PARAMS)],
        ['a badge to the header before it', badge(BEFORE_PARAMS), header(leafCell('group_name'))],
        [
            'the first header to the badge beside the selection column',
            header(leafCell('dock_visible')),
            badge(BY_SELECTION),
        ],
    ])('Shift+Tab goes from %s', (_case, from, expected) => {
        expect(headerTabTarget(grid.api, BADGES, from, true)).toEqual(expected);
    });

    it('goes from the last badge into the body, at the first displayed column', () => {
        expect(headerTabTarget(grid.api, BADGES, badge(LAST), false)).toEqual({
            kind: 'body',
            column: grid.column('selection'),
        });
    });

    it('leaves the last badge to the browser when the table has no rows', () => {
        expect(headerTabTarget(fakeGrid(LAYOUT, { rowCount: 0 }).api, BADGES, badge(LAST), false)).toBeNull();
    });

    it('takes Shift+Tab from a badge opening the header to what precedes the grid', () => {
        expect(headerTabTarget(grid.api, BADGES, badge(BY_SELECTION), true)).toEqual({ kind: 'beforeGrid' });
    });

    it('leaves Shift+Tab from the first header with nothing before it to ag-grid', () => {
        expect(headerTabTarget(grid.api, [], header(leafCell('dock_visible')), true)).toBeNull();
    });

    it('places badges by their neighbours, whatever order the badge list is in', () => {
        const shuffled: readonly HeaderBadgeBoundary[] = [BADGES[LAST], BADGES[BEFORE_PARAMS]];

        expect(headerTabTarget(grid.api, shuffled, header(leafCell('group_name')), false)).toEqual(badge(1));
        expect(headerTabTarget(grid.api, shuffled, header(leafCell('expression')), false)).toEqual(badge(0));
    });
});

describe('badgeClosingHeader', () => {
    it('is the badge past the last column, which Shift+Tab from the body reaches first', () => {
        expect(badgeClosingHeader(grid.api, [{ prevColId: 'expression', nextColId: null }])).toEqual({
            kind: 'badge',
            badgeIndex: 0,
        });
    });

    it('is null when the header ends in a header cell', () => {
        expect(badgeClosingHeader(grid.api, [{ prevColId: 'group_name', nextColId: 'field_a' }])).toBeNull();
    });
});

describe('stopPastActionlessHeader', () => {
    it('hands the focus from the selection header to the stop after it', () => {
        expect(stopPastActionlessHeader(grid.api, [], grid.column('selection'))).toEqual({
            kind: 'header',
            position: leafCell('dock_visible'),
        });
    });

    it('hands it to a badge that comes first', () => {
        const badges = [{ prevColId: 'selection', nextColId: 'dock_visible' }];

        expect(stopPastActionlessHeader(grid.api, badges, grid.column('selection'))).toEqual({
            kind: 'badge',
            badgeIndex: 0,
        });
    });

    it('leaves any other header alone', () => {
        expect(stopPastActionlessHeader(grid.api, [], grid.column('group_name'))).toBeNull();
    });
});
