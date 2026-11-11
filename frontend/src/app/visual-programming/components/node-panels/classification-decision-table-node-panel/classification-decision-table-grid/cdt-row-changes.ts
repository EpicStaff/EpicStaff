import { NodeType } from '@shared/models';

import { CdtSection } from '../../../../core/models/cdt-section.model';
import { ConditionGroup } from '../../../../core/models/decision-table.model';
import { toDisplayExpression } from '../../../../utils/condition-expression.helper';
import { GroupFieldColumns, UnionNodeDiffState } from '../../../../utils/diff';
import {
    ConditionGroupGridRowChanges,
    conditionGroupGridRowChanges,
    RemovedGroupRow,
    removedGroupRow,
} from '../../shared/condition-group-row-marks/condition-group-row-marks';
import { CDT_COLUMN_KIND, CDT_FIELD_PREFIX, CDT_MANIP_PREFIX } from '../cdt.constants';

/**
 * The columns of the Classification Decision Table grid, by the group fields the diff compares, in the grid's default
 * order, each cell by its column id; a field column (a param of the expression or the manipulation) is named by its
 * field. A group's section shows as the group bracket left of the rows ("Group"), and its route target as the route
 * code's connection on the canvas: only a row tooltip names them. Expressions and manipulations show their variables as
 * the cells do (`@amount`).
 */
const CDT_COLUMNS: GroupFieldColumns = {
    section: { name: 'Group' },
    dock_visible: { name: 'Enable', colId: 'dock_visible' },
    expression: { name: 'Expression', colId: CDT_COLUMN_KIND.EXPRESSION, shownText: toDisplayExpression },
    field_expressions: { colIdOfKey: (field) => `${CDT_FIELD_PREFIX}${field}`, shownText: toDisplayExpression },
    prompt_id: { name: 'Prompt ID', colId: 'prompt_id' },
    manipulation: { name: 'Manipulation', colId: CDT_COLUMN_KIND.MANIPULATION, shownText: toDisplayExpression },
    field_manipulations: { colIdOfKey: (field) => `${CDT_MANIP_PREFIX}${field}`, shownText: toDisplayExpression },
    route_code: { name: 'Route Code', colId: 'route_code' },
    continue_flag: { name: 'Continue', colId: 'continue_flag' },
    next_node: { name: 'Next Node' },
};

/**
 * What a restore does to the rows of a Classification Decision Table grid (Changes tab of a version preview); `null`
 * when the node shows no field marks or no row is marked. `groups` and `sections` are the version's, as the panel
 * holds them: a removed group joins the version section of its canvas section's name, if there is one.
 * `nodeIdOfKey` finds the canvas node a removed group routes to.
 */
export function cdtRowChanges(
    diff: UnionNodeDiffState | null,
    groups: readonly ConditionGroup[],
    sections: readonly CdtSection[],
    nodeIdOfKey: (key: string) => string | null
): ConditionGroupGridRowChanges | null {
    return conditionGroupGridRowChanges(
        NodeType.CLASSIFICATION_TABLE,
        diff,
        groups,
        CDT_COLUMNS,
        ({ name, group }): RemovedGroupRow => {
            const nextNode = group['next_node'];
            const sectionName = group['section'];
            return removedGroupRow({
                group_name: name,
                group_type: 'simple',
                conditions: [],
                expression: textOrNull(group['expression']),
                prompt_id: textOrNull(group['prompt_id']),
                manipulation: textOrNull(group['manipulation']),
                continue_flag: group['continue_flag'] === true,
                route_code: textOrNull(group['route_code']),
                section: sections.find((section) => section.name === sectionName)?.id ?? null,
                next_node: typeof nextNode === 'string' ? nodeIdOfKey(nextNode) : null,
                dock_visible: group['dock_visible'] !== false,
                field_expressions: textMap(group['field_expressions']),
                field_manipulations: textMap(group['field_manipulations']),
            });
        }
    );
}

/**
 * The grid's rows with the removed ones put in: each after the last row of its section, so it folds with that section;
 * one without a section at the end. One whose section has no rows left goes to the end without its section: that
 * section shows no bracket to unfold it by. Removed rows keep their canvas order.
 */
export function withRemovedRows(
    rows: readonly ConditionGroup[],
    removed: readonly RemovedGroupRow[]
): ConditionGroup[] {
    const shown = [...rows];
    for (const row of removed) {
        const lastOfSection = row.section ? lastIndexOfSection(shown, row.section) : -1;
        if (lastOfSection === -1) shown.push(row.section ? { ...row, section: null } : row);
        else shown.splice(lastOfSection + 1, 0, row);
    }
    return shown;
}

function lastIndexOfSection(rows: readonly ConditionGroup[], section: string): number {
    for (let index = rows.length - 1; index >= 0; index--) {
        if (rows[index].section === section) return index;
    }
    return -1;
}

function textOrNull(value: unknown): string | null {
    return typeof value === 'string' ? value : null;
}

function textMap(value: unknown): Record<string, string> {
    return value !== null && typeof value === 'object' && !Array.isArray(value)
        ? (value as Record<string, string>)
        : {};
}
