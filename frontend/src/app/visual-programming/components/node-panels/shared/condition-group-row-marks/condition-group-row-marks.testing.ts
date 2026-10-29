import { NodeType } from '@shared/models';

import { ConditionGroup } from '../../../../core/models/decision-table.model';
import {
    ClassificationDecisionTableNodeModel,
    DecisionTableNodeModel,
    NodeModel,
} from '../../../../core/models/node.model';
import { ConditionGroupRowMark, DisplaySegment, UnionNodeDiffState } from '../../../../utils/diff';
import { diffProjections } from '../../../../utils/diff/diff-fields';
import { projectNode } from '../../../../utils/diff/semantic-projections';
import { liveNodeOfType } from '../../node-panel-diff.testing';
import {
    CONDITION_GROUP_ROW_CLASS,
    ConditionGroupCellTooltip,
    ConditionGroupGridRowChanges,
    removedGroupRow,
} from './condition-group-row-marks';

/**
 * The diff a panel gets for a decision table whose groups a restore turns from `canvasGroups` into `versionGroups`:
 * the real diff of the two sides, keys as the diff writes them. Node references are compared by canvas id.
 */
export function conditionGroupsDiff(
    type: NodeType.TABLE | NodeType.CLASSIFICATION_TABLE,
    canvasGroups: ConditionGroup[],
    versionGroups: ConditionGroup[]
): UnionNodeDiffState {
    const context = { nodeKey: (canvasId: string | null | undefined) => canvasId ?? null };
    const canvasNode = tableNodeWith(type, canvasGroups);
    return {
        status: 'changed',
        fields: diffProjections(
            projectNode(canvasNode, context),
            projectNode(tableNodeWith(type, versionGroups), context)
        ),
        missingReferences: [],
        currentNode: canvasNode,
    };
}

/** The live graph fixture's decision table of `type` with `groups`. */
function tableNodeWith(type: NodeType.TABLE | NodeType.CLASSIFICATION_TABLE, groups: ConditionGroup[]): NodeModel {
    const node = liveNodeOfType(type) as DecisionTableNodeModel | ClassificationDecisionTableNodeModel;
    return { ...node, data: { ...node.data, table: { ...node.data.table, condition_groups: groups } } } as NodeModel;
}

/**
 * Row changes as a panel gives them to its grid: the marks by the groups the grid is given (the same objects), then
 * the groups a restore removes.
 */
export function gridRowChanges(
    marks: readonly (readonly [ConditionGroup, ConditionGroupRowMark])[],
    removed: ConditionGroup[] = []
): ConditionGroupGridRowChanges {
    return { marks: new Map(marks), removed: removed.map(removedGroupRow) };
}

/** A shown row of a decision table grid: the name in its name cell as a user sees it, and its row mark. */
export interface ShownGridRow {
    name: string;
    mark: 'changed' | 'added' | 'removed' | null;
}

/** The rows a grid shows, top to bottom, each with its mark. */
export function shownGridRows(host: HTMLElement): ShownGridRow[] {
    const rows = Array.from(host.querySelectorAll<HTMLElement>('.ag-row[row-index]')).sort(
        (first, second) => Number(first.getAttribute('row-index')) - Number(second.getAttribute('row-index'))
    );
    return rows.map((row) => ({ name: visibleNameOf(row), mark: markOf(row) }));
}

/** What a screen reader hears before the name of the row at `rowIndex` (hidden from sight); `null` for nothing. */
export function rowStatusOf(host: HTMLElement, rowIndex: number): string | null {
    return nameCellOf(rowOf(host, rowIndex)).querySelector('.visually-hidden')?.textContent?.trim() ?? null;
}

/** The text of the row tooltip shown, or `null` when none is open. */
export function shownRowTooltip(): string | null {
    return document.querySelector('.diff-field-mark__tooltip-hint')?.textContent?.trim() ?? null;
}

/**
 * The tooltip shown, as one text: the row summary, or the label and the cell's current value with its struck parts
 * in `~~` ("Current canvas: x > ~~1~~"); `null` when none is open.
 */
export function shownTooltipText(): string | null {
    const tooltip = document.querySelector('.diff-field-mark__tooltip');
    if (!tooltip) return null;
    const hint = tooltip.querySelector('.diff-field-mark__tooltip-hint');
    if (hint) return hint.textContent?.trim() ?? '';
    const label = tooltip.querySelector('.diff-field-mark__tooltip-label')?.textContent?.trim();
    const segments = Array.from(tooltip.querySelectorAll('.diff-field-mark__tooltip-value > span'), (span) => ({
        text: span.textContent ?? '',
        struck: span.classList.contains('diff-field-mark__struck'),
    }));
    return `${label}: ${struckText(segments)}`;
}

/** A cell tooltip as one text: the row summary, or the current value with its struck parts in `~~` (`x > ~~1~~`). */
export function cellTooltipText(tooltip: ConditionGroupCellTooltip | null): string | null {
    if (tooltip === null) return null;
    return 'hint' in tooltip ? tooltip.hint : struckText(tooltip.segments);
}

/** A row mark as a test writes it: no cell of its own changed. */
export function rowMark(status: ConditionGroupRowMark['status'], hint: string | null = null): ConditionGroupRowMark {
    return { status, hint, cells: new Map() };
}

function struckText(segments: readonly DisplaySegment[]): string {
    return segments.map(({ text, struck }) => (struck ? `~~${text}~~` : text)).join('');
}

/** A cell of the row at `rowIndex`, by its column id (any characters a field key may hold). */
export function gridCell(host: HTMLElement, rowIndex: number, colId: string): HTMLElement {
    const cell = host.querySelector<HTMLElement>(
        `.ag-row[row-index="${rowIndex}"] [role="gridcell"][col-id="${CSS.escape(colId)}"]`
    );
    if (!cell) throw new Error(`no ${colId} cell in row ${rowIndex}`);
    return cell;
}

export function rowOf(host: HTMLElement, rowIndex: number): HTMLElement {
    const row = host.querySelector<HTMLElement>(`.ag-row[row-index="${rowIndex}"]`);
    if (!row) throw new Error(`no row ${rowIndex}`);
    return row;
}

function markOf(row: HTMLElement): ShownGridRow['mark'] {
    const entry = Object.entries(CONDITION_GROUP_ROW_CLASS).find(([, rowClass]) => row.classList.contains(rowClass));
    return (entry?.[0] as ShownGridRow['mark'] | undefined) ?? null;
}

function nameCellOf(row: HTMLElement): HTMLElement {
    const cell = row.querySelector<HTMLElement>('[role="gridcell"][col-id="group_name"]');
    if (!cell) throw new Error('no name cell');
    return cell;
}

/** The name as the cell shows it, without the text only screen readers hear. */
function visibleNameOf(row: HTMLElement): string {
    const cell = nameCellOf(row).cloneNode(true) as HTMLElement;
    cell.querySelectorAll('.visually-hidden').forEach((hidden) => hidden.remove());
    return cell.textContent?.trim() ?? '';
}
