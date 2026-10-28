import { NodeType } from '@shared/models';
import { ColDef, ColGroupDef, EditableCallbackParams } from 'ag-grid-community';

import { ConditionGroup } from '../../../../core/models/decision-table.model';
import { NodeModel } from '../../../../core/models/node.model';
import {
    conditionGroupDiffKeys,
    conditionGroupRowChanges,
    ConditionGroupRowMark,
    DisplaySegment,
    GroupFieldColumns,
    UnionNodeDiffState,
} from '../../../../utils/diff';

// The row marks of a decision table grid (Decision Table, Classification Decision Table) on the Changes tab of a
// version preview: a row a restore changes gets a yellow pen badge and yellow text, one it adds a green plus badge and
// green text, and the groups it removes show as extra rows with a red bin badge, red, struck and faded, that can never
// be edited, selected or saved.

/** A group only the canvas has, as the grid shows it after the version's rows: never part of the table's rows. */
export type RemovedGroupRow = ConditionGroup & { readonly removedByRestore: true };

/** What a restore does to the rows of a decision table grid; `null` anywhere but the Changes tab. */
export interface ConditionGroupGridRowChanges {
    /**
     * For the version rows a restore changes or adds, by the group itself as the panel gives it to its grid: group
     * names may repeat, so a row is never found by its name.
     */
    marks: ReadonlyMap<ConditionGroup, ConditionGroupRowMark>;
    /** The groups a restore removes, in their canvas order. */
    removed: readonly RemovedGroupRow[];
}

/** A group only the canvas has, for a grid to show as a removed row. */
export interface RemovedGroupSource {
    /** Its name on the canvas. */
    name: string;
    /** The group as the diff compares it (`semantic-projections.ts`), its node references as match keys. */
    group: Readonly<Record<string, unknown>>;
    /** The row number the canvas grid shows on it; `null` when the canvas side is not known. */
    rowNumber: number | null;
}

/** The row classes the grids style (`grid-row-marks` in `styles/_diff-value-mark.scss`). */
export const CONDITION_GROUP_ROW_CLASS = {
    changed: 'condition-group-row--changed',
    added: 'condition-group-row--added',
    removed: 'condition-group-row--removed',
} as const;

/**
 * What a restore does to the rows of a decision table grid (Changes tab of a version preview); `null` when the node
 * shows no field marks or no row is marked. `groups` are the version's, as the panel gives them to its grid; each is
 * matched to its row changes by its key in the diff (`conditionGroupDiffKeys`), as the diff keys it. A changed row
 * lists its changed fields by `columns`; `removedRow` turns a group only the canvas has into the grid's row.
 */
export function conditionGroupGridRowChanges(
    type: NodeType.TABLE | NodeType.CLASSIFICATION_TABLE,
    diff: UnionNodeDiffState | null,
    groups: readonly ConditionGroup[],
    columns: GroupFieldColumns,
    removedRow: (source: RemovedGroupSource) => RemovedGroupRow
): ConditionGroupGridRowChanges | null {
    const versionGroups = conditionGroupDiffKeys(type, groups).filter(
        (keyed): keyed is { group: ConditionGroup; key: string } => keyed.key !== null
    );
    const canvasGroups = conditionGroupDiffKeys(type, canvasGroupsOf(diff?.currentNode));
    const canvasRowNumbers = new Map<string, number>();
    const canvasNames = new Map<string, string>();
    canvasGroups.forEach(({ group, key }, index) => {
        if (key === null) return;
        canvasRowNumbers.set(key, index + 1);
        canvasNames.set(key, group.group_name);
    });
    const changes = conditionGroupRowChanges(
        diff,
        versionGroups.map(({ key }) => key),
        columns,
        canvasRowNumbers
    );
    if (changes === null) return null;
    const marks = new Map<ConditionGroup, ConditionGroupRowMark>();
    for (const { group, key } of versionGroups) {
        const mark = changes.rows.get(key);
        if (mark) marks.set(group, mark);
    }
    return {
        marks,
        removed: changes.removed.map(({ key, group }) =>
            removedRow({ name: canvasNames.get(key) ?? key, group, rowNumber: canvasRowNumbers.get(key) ?? null })
        ),
    };
}

export function isRemovedGroupRow(data: unknown): data is RemovedGroupRow {
    return (data as Partial<RemovedGroupRow> | null | undefined)?.removedByRestore === true;
}

/** A canvas group as an extra grid row. */
export function removedGroupRow(group: ConditionGroup): RemovedGroupRow {
    return { ...group, removedByRestore: true };
}

/** The mark of a version row; `null` for a removed row or a row a restore keeps. */
export function rowMarkOf(changes: ConditionGroupGridRowChanges | null, data: unknown): ConditionGroupRowMark | null {
    if (changes === null || isRemovedGroupRow(data)) return null;
    return changes.marks.get(data as ConditionGroup) ?? null;
}

/**
 * What the tooltip over a cell of a changed row shows: the cell's own change (`segments`, the current canvas value as
 * the cell shows it, the part a restore replaces struck), or, for a cell whose value a restore keeps, the row's
 * summary (`hint`: "Changed columns: … Moved …").
 */
export type ConditionGroupCellTooltip = { segments: readonly DisplaySegment[] } | { hint: string };

/**
 * The tooltip over the cell of column `colId` (ag-grid `col-id`; `null` for none) of a row; `null` for a row a restore
 * adds, removes or keeps, and outside the Changes tab.
 */
export function cellTooltipOf(
    changes: ConditionGroupGridRowChanges | null,
    data: unknown,
    colId: string | null
): ConditionGroupCellTooltip | null {
    const mark = rowMarkOf(changes, data);
    if (mark?.status !== 'changed' || mark.hint === null) return null;
    const segments = colId === null ? undefined : mark.cells.get(colId);
    return segments ? { segments } : { hint: mark.hint };
}

/** The class of a row (ag-grid `getRowClass`); none for a row a restore keeps and outside the Changes tab. */
export function rowMarkClass(changes: ConditionGroupGridRowChanges | null, data: unknown): string | undefined {
    if (changes === null) return undefined;
    if (isRemovedGroupRow(data)) return CONDITION_GROUP_ROW_CLASS.removed;
    const mark = rowMarkOf(changes, data);
    return mark ? CONDITION_GROUP_ROW_CLASS[mark.status] : undefined;
}

/** What a screen reader hears before a marked row's name: the row's status, and its tooltip for a changed row. */
export function rowStatusText(changes: ConditionGroupGridRowChanges | null, data: unknown): string | null {
    if (changes === null) return null;
    if (isRemovedGroupRow(data)) return 'Restore removes this condition.';
    const mark = rowMarkOf(changes, data);
    if (mark === null) return null;
    return mark.status === 'added' ? 'Restore adds this condition.' : `Restore changes this condition. ${mark.hint}`;
}

/** The column definitions with no cell of a removed row editable; other rows keep what each column allows. */
export function lockRemovedRows<TDefinition extends ColDef | ColGroupDef>(definitions: TDefinition[]): TDefinition[] {
    return definitions.map((definition) => {
        if ('children' in definition) return { ...definition, children: lockRemovedRows(definition.children) };
        const editable = definition.editable;
        if (!editable) return definition;
        return {
            ...definition,
            editable: (params: EditableCallbackParams) =>
                !isRemovedGroupRow(params.data) && (typeof editable === 'function' ? editable(params) : editable),
        };
    });
}

/** The condition groups of the canvas side of a decision table; none when that side is not known. */
function canvasGroupsOf(node: NodeModel | undefined): readonly ConditionGroup[] {
    return node?.type === NodeType.TABLE || node?.type === NodeType.CLASSIFICATION_TABLE
        ? (node.data.table.condition_groups ?? [])
        : [];
}
