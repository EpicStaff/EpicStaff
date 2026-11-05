import {
    Column,
    ColumnGroup,
    GridApi,
    HeaderPosition,
    NavigateToNextHeaderParams,
    TabToNextHeaderParams,
} from 'ag-grid-community';

/**
 * Columns whose header cell holds no control and nothing to read, so keyboard
 * navigation goes past it. The row-selection header only shows a count once rows
 * are selected; its checkboxes live in the body cells, which stay navigable.
 */
const ACTIONLESS_HEADER_COL_IDS: ReadonlySet<string> = new Set(['selection']);

function isColumn(column: Column | ColumnGroup): column is Column {
    return 'getColId' in column;
}

function isActionlessHeader(column: Column | ColumnGroup | null | undefined): column is Column {
    return !!column && isColumn(column) && ACTIONLESS_HEADER_COL_IDS.has(column.getColId());
}

/** Whether the keyboard stops on `column`'s own header cell. */
function hasNavigableHeader(column: Column): boolean {
    return !ACTIONLESS_HEADER_COL_IDS.has(column.getColId());
}

/** The first column from `column` on, in the direction of travel, whose header is worth a stop. */
function navigableColumnFrom(api: GridApi, column: Column, backwards: boolean): Column | null {
    let candidate: Column | null = column;
    while (candidate && isActionlessHeader(candidate)) {
        candidate = backwards ? api.getDisplayedColBefore(candidate) : api.getDisplayedColAfter(candidate);
    }
    return candidate;
}

/** `position`, or the header past it when it is actionless; null when nothing lies past it. */
function pastActionlessHeader(api: GridApi, position: HeaderPosition, backwards: boolean): HeaderPosition | null {
    if (!isActionlessHeader(position.column)) return position;
    const column = navigableColumnFrom(api, position.column, backwards);
    // An actionless header spans the full header height, so its row is the leaf row, valid for any column.
    return column ? { headerRowIndex: position.headerRowIndex, column } : null;
}

/**
 * The header row ag-grid gives `column`'s own cell: the leaf row, one row below each
 * group above it. ag-grid pads every column to the same depth, so this holds for a
 * column outside any group too — its cell spans the rows above, where its padding
 * group is not rendered, but ag-grid still places it on the leaf row.
 */
function leafRowIndexOf(column: Column): number {
    let rowIndex = 0;
    for (let group = column.getParent(); group; group = group.getParent()) rowIndex++;
    return rowIndex;
}

/** The header row a header cell sits in. */
export function headerPositionOf(column: Column | ColumnGroup): HeaderPosition {
    const headerRowIndex = isColumn(column) ? leafRowIndexOf(column) : column.getProvidedColumnGroup().getLevel();
    return { headerRowIndex, column };
}

/**
 * The header `column` shows in `headerRowIndex`, as ag-grid's own
 * `getHeaderIndexToFocus` picks it: its own cell on the leaf row; above it, the group
 * at that level — unless that is a padding group over a column spanning the header
 * height, which is not rendered, so the column's own (spanning) cell.
 */
function headerOfColumnAtRow(column: Column, headerRowIndex: number): HeaderPosition {
    const leafRowIndex = leafRowIndexOf(column);
    if (headerRowIndex >= leafRowIndex) return { headerRowIndex, column };
    let group = column.getParent();
    while (group && group.getProvidedColumnGroup().getLevel() > headerRowIndex) group = group.getParent();
    if (!group || (group.isPadding() && column.isSpanHeaderHeight())) return { headerRowIndex: leafRowIndex, column };
    return { headerRowIndex: group.getProvidedColumnGroup().getLevel(), column: group };
}

/**
 * The next header in the same row for the arrow keys, past actionless ones; null at
 * the end of the row. Worked out from the header that really has the focus
 * (`previousHeaderPosition`), not from ag-grid's `nextHeaderPosition`: ag-grid derives
 * that from a header row it remembers, which goes stale when the focus reaches a
 * header through `setFocusedHeader` — as every Tab in the header does here.
 */
function headerBesideInRow(api: GridApi, position: HeaderPosition, backwards: boolean): HeaderPosition | null {
    const { column, headerRowIndex } = position;
    // A group is left from its first or last leaf, whichever faces the direction of travel.
    const leafColumns = isColumn(column) ? [column] : column.getDisplayedLeafColumns();
    const edgeColumn = backwards ? leafColumns[0] : leafColumns[leafColumns.length - 1];
    if (!edgeColumn) return null;
    const beside = backwards ? api.getDisplayedColBefore(edgeColumn) : api.getDisplayedColAfter(edgeColumn);
    const navigable = beside ? navigableColumnFrom(api, beside, backwards) : null;
    return navigable ? headerOfColumnAtRow(navigable, headerRowIndex) : null;
}

/**
 * Where a hidden-column badge sits on the leaf header row: on the boundary between
 * these two visible columns. Either is null at the edge of the table.
 */
export interface HeaderBadgeBoundary {
    readonly prevColId: string | null;
    readonly nextColId: string | null;
}

/** A Tab stop in the header: a header cell, or a hidden-column badge by its index in the badge list. */
export type HeaderTabStop =
    | { readonly kind: 'header'; readonly position: HeaderPosition }
    | { readonly kind: 'badge'; readonly badgeIndex: number };

/**
 * Where Tab takes the focus: a header stop, the first body cell of `column`, or out
 * of the grid to whatever precedes it.
 */
export type HeaderTabTarget =
    | HeaderTabStop
    | { readonly kind: 'body'; readonly column: Column }
    | { readonly kind: 'beforeGrid' };

/** A place in the header's Tab order; actionless headers hold a place but are no stop. */
interface OrderedStop {
    readonly stop: HeaderTabStop;
    readonly navigable: boolean;
}

/**
 * The index of the displayed column a badge sits before (the column count when it
 * sits past the last one). Compared by index, not id, because the column beside a
 * badge may be one whose header is no Tab stop. Null when neither neighbour is displayed.
 */
function badgeBoundaryIndex(badge: HeaderBadgeBoundary, columnIndexById: ReadonlyMap<string, number>): number | null {
    const nextIndex = badge.nextColId === null ? undefined : columnIndexById.get(badge.nextColId);
    if (nextIndex !== undefined) return nextIndex;
    const prevIndex = badge.prevColId === null ? undefined : columnIndexById.get(badge.prevColId);
    return prevIndex === undefined ? null : prevIndex + 1;
}

/** The rendered group cells that start at `column`, outermost first. Padding groups render no cell here. */
function groupCellsOpeningAt(column: Column): HeaderPosition[] {
    const cells: HeaderPosition[] = [];
    for (let group = column.getParent(); group; group = group.getParent()) {
        if (!group.isPadding() && group.getDisplayedLeafColumns()[0] === column) {
            cells.unshift({ headerRowIndex: group.getProvidedColumnGroup().getLevel(), column: group });
        }
    }
    return cells;
}

/**
 * The whole header as one Tab order, left to right in reading order: each group cell
 * just before the first column under it, each column's own cell, and each badge on
 * the boundary it sits on. Every cell is visited once — ag-grid's own order walks the
 * header row by row and so visits a cell spanning both rows twice, and it needs a
 * remembered row to tell those visits apart. The badges are rendered after the grid,
 * so the DOM order cannot give their place either.
 */
function orderedHeaderStops(api: GridApi, badges: readonly HeaderBadgeBoundary[]): OrderedStop[] {
    const columns = api.getAllDisplayedColumns();
    const columnIndexById = new Map(columns.map((column, index) => [column.getColId(), index]));
    const badgeIndexesByBoundary = new Map<number, number[]>();
    badges.forEach((badge, badgeIndex) => {
        const boundary = badgeBoundaryIndex(badge, columnIndexById);
        if (boundary === null) return;
        badgeIndexesByBoundary.set(boundary, [...(badgeIndexesByBoundary.get(boundary) ?? []), badgeIndex]);
    });

    const ordered: OrderedStop[] = [];
    for (let index = 0; index <= columns.length; index++) {
        for (const badgeIndex of badgeIndexesByBoundary.get(index) ?? []) {
            ordered.push({ stop: { kind: 'badge', badgeIndex }, navigable: true });
        }
        const column: Column | undefined = columns[index];
        if (!column) continue;
        for (const position of groupCellsOpeningAt(column)) {
            ordered.push({ stop: { kind: 'header', position }, navigable: true });
        }
        ordered.push({
            stop: { kind: 'header', position: { headerRowIndex: leafRowIndexOf(column), column } },
            navigable: hasNavigableHeader(column),
        });
    }
    return ordered;
}

function isSameTabStop(stop: HeaderTabStop, other: HeaderTabStop): boolean {
    if (stop.kind === 'badge' || other.kind === 'badge') {
        return stop.kind === 'badge' && other.kind === 'badge' && stop.badgeIndex === other.badgeIndex;
    }
    return stop.position.column === other.position.column;
}

/**
 * The stop next to `from` in the direction of travel, past actionless headers; null
 * past either end, undefined when `from` is not in the order at all.
 */
function stopBeside(
    ordered: readonly OrderedStop[],
    from: HeaderTabStop,
    backwards: boolean
): HeaderTabStop | null | undefined {
    const fromIndex = ordered.findIndex((entry) => isSameTabStop(entry.stop, from));
    if (fromIndex === -1) return undefined;
    const step = backwards ? -1 : 1;
    for (let index = fromIndex + step; index >= 0 && index < ordered.length; index += step) {
        if (ordered[index].navigable) return ordered[index].stop;
    }
    return null;
}

/** Past the last stop: the first body cell; null without rows, where the focus leaves the grid. */
function firstBodyCell(api: GridApi): HeaderTabTarget | null {
    const firstColumn = api.getAllDisplayedColumns()[0];
    return firstColumn && api.getDisplayedRowCount() > 0 ? { kind: 'body', column: firstColumn } : null;
}

/**
 * Where Tab (Shift+Tab when `backwards`) takes the focus from a header cell or a
 * hidden-column badge, in the order of `orderedHeaderStops`; null to leave the key
 * to ag-grid, which then leaves the grid the way `tabPastActionlessHeaders` does.
 */
export function headerTabTarget(
    api: GridApi,
    badges: readonly HeaderBadgeBoundary[],
    from: HeaderTabStop,
    backwards: boolean
): HeaderTabTarget | null {
    const next = stopBeside(orderedHeaderStops(api, badges), from, backwards);
    if (next) return next;
    if (next === undefined) return null;
    if (!backwards) return firstBodyCell(api);
    // ag-grid can take the focus out of the grid from a header, not from a badge rendered after it.
    return from.kind === 'badge' ? { kind: 'beforeGrid' } : null;
}

/**
 * Where Shift+Tab from the first body cell goes when the header ends in a badge.
 * ag-grid would focus the last header cell and skip it; null otherwise.
 */
export function badgeClosingHeader(api: GridApi, badges: readonly HeaderBadgeBoundary[]): HeaderTabTarget | null {
    const ordered = orderedHeaderStops(api, badges);
    const last = ordered[ordered.length - 1]?.stop;
    return last?.kind === 'badge' ? last : null;
}

/**
 * Where the focus moves on from an actionless header reached by a path the
 * callbacks never see — Tab into the grid, ArrowUp from a body cell, or a click:
 * the next stop after it. Null for any other header, or with nothing after it.
 */
export function stopPastActionlessHeader(
    api: GridApi,
    badges: readonly HeaderBadgeBoundary[],
    column: Column | ColumnGroup
): HeaderTabTarget | null {
    if (!isActionlessHeader(column)) return null;
    return (
        stopBeside(orderedHeaderStops(api, badges), { kind: 'header', position: headerPositionOf(column) }, false) ??
        null
    );
}

/**
 * `tabToNextHeader`: the same order as `headerTabTarget`, without the badges. The
 * component routes Tab in the header itself, so this is reached only when it leaves
 * the key to ag-grid: at the ends, past the last header into the body
 * (`headerRowIndex: -1` makes ag-grid focus the first body cell of that column), and
 * from the first header out of the grid. Returning `false` forward would push the
 * focus out of the grid, past the body.
 */
export function tabPastActionlessHeaders(params: TabToNextHeaderParams): HeaderPosition | boolean {
    const current = params.previousHeaderPosition;
    if (!current) return false;
    const next = stopBeside(
        orderedHeaderStops(params.api, []),
        { kind: 'header', position: current },
        params.backwards
    );
    if (next?.kind === 'header') return next.position;
    if (next === null && !params.backwards) {
        // The selection column's header is skipped, but its body cells are navigable.
        const firstColumn = params.api.getAllDisplayedColumns()[0];
        if (firstColumn) return { headerRowIndex: -1, column: firstColumn };
    }
    return false;
}

/** `navigateToNextHeader`: the arrow keys skip actionless headers, or stay put when nothing lies past one. */
export function navigatePastActionlessHeaders(params: NavigateToNextHeaderParams): HeaderPosition | null {
    const current = params.previousHeaderPosition;
    const sideways = params.key === 'ArrowLeft' || params.key === 'ArrowRight';
    // Left and Right stay in the focused header's row; see `headerBesideInRow` for why ag-grid's pick is not used.
    if (sideways && current) return headerBesideInRow(params.api, current, params.key === 'ArrowLeft');
    const next = params.nextHeaderPosition;
    if (!next) return null;
    return pastActionlessHeader(params.api, next, params.key === 'ArrowLeft');
}

/**
 * ag-grid focuses a header *cell*, not the controls inside it, and its Tab moves on
 * to the next header, so a header's button is reachable from the keyboard only
 * through the cell. Enter or Space on the focused cell runs `activate`, which must
 * do what a click on that control does. Returns the function that stops listening.
 */
export function listenForHeaderActivation(eGridHeader: HTMLElement, activate: () => void): () => void {
    const onKeydown = (event: KeyboardEvent): void => {
        // A key pressed on a control inside the cell is that control's own business.
        if (event.target !== eGridHeader) return;
        if (event.key !== 'Enter' && event.key !== ' ') return;
        // Modified keys stay ag-grid's; a held key does not open and close the menu over and over.
        if (event.ctrlKey || event.metaKey || event.altKey || event.shiftKey || event.repeat) return;
        // Space would scroll the panel; neither key may reach the flow editor's own shortcuts.
        event.preventDefault();
        event.stopPropagation();
        activate();
    };
    eGridHeader.addEventListener('keydown', onKeydown);
    return () => eGridHeader.removeEventListener('keydown', onKeydown);
}

/**
 * The column whose header should take the focus once `columns` are hidden: the one
 * after them, else the one before. Hiding removes the focused header from the DOM,
 * and the focus would otherwise fall to `<body>`, where Delete deletes the selected
 * flow node.
 */
export function headerBesideColumns(api: GridApi, columns: readonly Column[]): Column | null {
    if (columns.length === 0) return null;
    return api.getDisplayedColAfter(columns[columns.length - 1]) ?? api.getDisplayedColBefore(columns[0]);
}
