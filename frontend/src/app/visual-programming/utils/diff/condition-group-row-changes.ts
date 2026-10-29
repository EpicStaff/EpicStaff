import { UnionNodeDiffState } from './build-union-flow-model';
import { DisplaySegment, fieldValueSegments, KeyedItemChange, keyedItemChanges } from './field-change-display';
import { isSameValue } from './normalize';

// What a restore does to the rows of a decision table grid (one row per condition group), for the row marks of the
// version diff. Display only; the diff engine never reads this.

/** How a grid shows a group field in one column. */
export interface GroupFieldColumn {
    /** The column's header; for a field no column shows, the name the row's tooltip gives it. */
    name: string;
    /** The grid's id of the column (ag-grid `colId`); none when no column shows the field. */
    colId?: string;
    /**
     * How the cell shows a text value (e.g. `variables.amount` as `@amount`): the cell's tooltip compares and strikes
     * the text as shown. Not set: as stored.
     */
    shownText?: (text: string) => string;
    /** How the cell shows a value as a whole (e.g. a node's name for its key): shown and struck as a whole. */
    format?: (value: unknown) => string;
}

/** How a grid shows a map group field as one column per key (the field columns of a Classification Decision Table). */
export interface GroupFieldKeyColumns {
    /** The grid's id of the column of a key; the column is named by the key. */
    colIdOfKey: (key: string) => string;
    /** How a cell shows a text value, as in `GroupFieldColumn`. */
    shownText?: (text: string) => string;
}

/** How a grid shows each group field the diff compares; a field it does not list marks nothing. */
export type GroupFieldColumns = Readonly<Record<string, GroupFieldColumn | GroupFieldKeyColumns>>;

/** What a restore does to one row of the version's groups. */
export interface ConditionGroupRowMark {
    /** `added`: only the version has the group. */
    status: 'changed' | 'added';
    /**
     * What the row's tooltip says, for a changed row: "Changed columns: Expression, Next Node." and, for a group whose
     * order a restore changes, "Moved (current canvas: position 2)."; `null` for an added row.
     */
    hint: string | null;
    /**
     * For a changed row, by column id: the tooltip of each cell whose value a restore changes, the current canvas value
     * as the cell shows it, the part a restore replaces struck. A cell not listed shows the row's `hint`. Empty for an
     * added row.
     */
    cells: ReadonlyMap<string, readonly DisplaySegment[]>;
}

/** A group only the canvas has: a restore removes it. */
export interface RemovedConditionGroup {
    /** Its key in the diff (`conditionGroupDiffKeys`), not always its name. */
    key: string;
    /** The group as the diff compares it (`semantic-projections.ts`), its node references as match keys. */
    group: Readonly<Record<string, unknown>>;
}

/** What a restore does to the rows of a decision table grid. */
export interface ConditionGroupRowChanges {
    /** By key in the diff, for the version's groups a restore changes or adds; a row it keeps has none. */
    rows: ReadonlyMap<string, ConditionGroupRowMark>;
    /** The groups only the canvas has, in their canvas order. */
    removed: readonly RemovedConditionGroup[];
}

const POSITION = 'position';

/**
 * What a restore does to each row of a decision table grid (Changes tab of a version preview); `null` when the node
 * shows no field marks or no row is marked.
 *
 * `versionOrder` holds the keys of the groups the diff compares on the version side, in order
 * (`conditionGroupDiffKeys`). A changed row lists the columns of its changed fields, named by `columns` in its
 * order, with the tooltip of each changed cell a column of `columns` shows; a field `columns` does not name marks
 * nothing, so a field the diff starts to compare shows up in the drift guard until its grid names it. A changed
 * `position` only marks a row when the group really moved (`movedKeys`): a shift caused by groups a restore adds or
 * removes is not a move. A moved row names its canvas place by `canvasRowNumbers` (by key) when the grid numbers its
 * rows other than the diff counts positions, else by its position in the diff.
 */
export function conditionGroupRowChanges(
    diff: UnionNodeDiffState | null,
    versionOrder: readonly string[],
    columns: GroupFieldColumns,
    canvasRowNumbers: ReadonlyMap<string, number> = new Map()
): ConditionGroupRowChanges | null {
    const items = keyedItemChanges(diff, 'condition_groups');
    if (items === null) return null;
    const itemByKey = new Map(items.map((item) => [item.key, item]));
    const currentPositions = canvasPositions(versionOrder, itemByKey);
    const currentOrder = [...currentPositions.keys()].sort(
        (left, right) => currentPositions.get(left)! - currentPositions.get(right)!
    );
    const moved = movedKeys(currentOrder, versionOrder);

    const rows = new Map<string, ConditionGroupRowMark>();
    for (const key of versionOrder) {
        const item = itemByKey.get(key);
        if (item?.status === 'added') {
            rows.set(key, { status: 'added', hint: null, cells: new Map() });
        } else if (item?.status === 'changed') {
            const changedColumns = columnsOf(item, columns);
            const canvasPlace = canvasRowNumbers.get(key) ?? currentPositions.get(key);
            const sentences = [
                changedColumns.length > 0 ? `Changed columns: ${changedColumns.join(', ')}.` : null,
                moved.has(key) ? `Moved (current canvas: position ${canvasPlace}).` : null,
            ].filter((sentence): sentence is string => sentence !== null);
            if (sentences.length > 0) {
                rows.set(key, { status: 'changed', hint: sentences.join(' '), cells: cellsOf(item, columns) });
            }
        }
    }
    const removed = currentOrder
        .map((key) => itemByKey.get(key))
        .filter((item): item is KeyedItemChange => item?.status === 'deleted')
        .map((item): RemovedConditionGroup => ({ key: item.key, group: asMap(item.current) }));

    return rows.size > 0 || removed.length > 0 ? { rows, removed } : null;
}

/**
 * The keys of the items both orders hold whose place relative to the other shared items differs: the ones outside
 * the longest run of shared items that keeps its order. Items only one side has are left out first, so the shift they
 * cause is no move. Of several longest runs the one ending earliest in the canvas order is kept: of two swapped
 * items, the one that comes first in the version (moved up) is the moved one.
 */
export function movedKeys(currentOrder: readonly string[], versionOrder: readonly string[]): Set<string> {
    const currentIndex = new Map(currentOrder.map((key, index) => [key, index]));
    const shared = versionOrder.filter((key) => currentIndex.has(key));
    const kept = longestIncreasingRun(shared.map((key) => currentIndex.get(key)!));
    return new Set(shared.filter((_, index) => !kept.has(index)));
}

/** For a map shown as one column per key: the keys a restore changes, adds or removes, version keys first. */
function changedKeyColumns(current: unknown, version: unknown): string[] {
    const currentMap = asMap(current);
    const versionMap = asMap(version);
    const keys = [
        ...Object.keys(versionMap),
        ...Object.keys(currentMap).filter((key) => !Object.hasOwn(versionMap, key)),
    ];
    return keys.filter((key) => !isSameValue(currentMap[key] ?? null, versionMap[key] ?? null));
}

/**
 * The canvas position of every canvas group: a changed `position` says it, a group a restore removes holds it, and a
 * group the version keeps in place has its version position.
 */
function canvasPositions(
    versionOrder: readonly string[],
    itemByKey: ReadonlyMap<string, KeyedItemChange>
): Map<string, number> {
    const positions = new Map<string, number>();
    versionOrder.forEach((key, index) => {
        const item = itemByKey.get(key);
        if (item?.status === 'added') return;
        const changedPosition = item?.fields.includes(POSITION) ? asMap(item.current)[POSITION] : undefined;
        positions.set(key, typeof changedPosition === 'number' ? changedPosition : index + 1);
    });
    for (const item of itemByKey.values()) {
        if (item.status !== 'deleted') continue;
        const position = asMap(item.current)[POSITION];
        positions.set(item.key, typeof position === 'number' ? position : Number.MAX_SAFE_INTEGER);
    }
    return positions;
}

/** The changed columns of a row, in the grid's order, each named once. */
function columnsOf(item: KeyedItemChange, columns: GroupFieldColumns): string[] {
    const current = asMap(item.current);
    const version = asMap(item.version);
    const names = Object.entries(columns)
        .filter(([field]) => item.fields.includes(field))
        .flatMap(([field, column]) =>
            'name' in column ? [column.name] : changedKeyColumns(current[field], version[field])
        );
    return [...new Set(names)];
}

/** The tooltip of each changed cell of a row, by column id; a field no column shows has none. */
function cellsOf(item: KeyedItemChange, columns: GroupFieldColumns): Map<string, readonly DisplaySegment[]> {
    const current = asMap(item.current);
    const version = asMap(item.version);
    const cells = new Map<string, readonly DisplaySegment[]>();
    for (const [field, column] of Object.entries(columns)) {
        if (!item.fields.includes(field)) continue;
        if ('name' in column) {
            if (column.colId !== undefined) {
                cells.set(column.colId, cellSegments(current[field], version[field], column));
            }
            continue;
        }
        const currentMap = asMap(current[field]);
        const versionMap = asMap(version[field]);
        for (const key of changedKeyColumns(currentMap, versionMap)) {
            cells.set(column.colIdOfKey(key), cellSegments(currentMap[key] ?? null, versionMap[key] ?? null, column));
        }
    }
    return cells;
}

/** The current value as its cell shows it, the part a restore replaces struck, cut as a field mark's tooltip. */
function cellSegments(
    current: unknown,
    version: unknown,
    { shownText, format }: Pick<GroupFieldColumn, 'shownText' | 'format'>
): DisplaySegment[] {
    const shown = (value: unknown): unknown => (shownText && typeof value === 'string' ? shownText(value) : value);
    return fieldValueSegments(null, shown(current), shown(version), undefined, format);
}

/** The indexes of one longest strictly increasing run of `values` (patience sorting, O(n log n)). */
function longestIncreasingRun(values: readonly number[]): Set<number> {
    // `tails[length - 1]`: the index of the smallest value that ends a run of that length so far.
    const tails: number[] = [];
    const previous: number[] = [];
    values.forEach((value, index) => {
        let low = 0;
        let high = tails.length;
        while (low < high) {
            const middle = (low + high) >> 1;
            if (values[tails[middle]] < value) low = middle + 1;
            else high = middle;
        }
        previous[index] = low > 0 ? tails[low - 1] : -1;
        tails[low] = index;
    });
    const run = new Set<number>();
    for (let index = tails.at(-1) ?? -1; index !== -1; index = previous[index]) run.add(index);
    return run;
}

function asMap(value: unknown): Record<string, unknown> {
    return value !== null && typeof value === 'object' && !Array.isArray(value)
        ? (value as Record<string, unknown>)
        : {};
}
