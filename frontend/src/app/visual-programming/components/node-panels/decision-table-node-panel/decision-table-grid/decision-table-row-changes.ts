import { NodeType } from '@shared/models';

import { Condition, ConditionGroup } from '../../../../core/models/decision-table.model';
import { GroupFieldColumns, UnionNodeDiffState } from '../../../../utils/diff';
import {
    ConditionGroupGridRowChanges,
    conditionGroupGridRowChanges,
    RemovedGroupRow,
    removedGroupRow,
} from '../../shared/condition-group-row-marks/condition-group-row-marks';

/**
 * The columns of the Decision Table grid, by the group fields the diff compares, in the grid's order, each cell by its
 * column id. The grid shows no group type and no conditions (a simple group's), so only a row tooltip names them, as
 * the model does. A Next Node cell shows the name of the node a route leads to, by `routeTarget`.
 */
function decisionTableColumns(routeTarget: (value: unknown) => string): GroupFieldColumns {
    return {
        group_type: { name: 'Group type' },
        conditions: { name: 'Conditions' },
        expression: { name: 'Expression', colId: 'expression' },
        manipulation: { name: 'Manipulation', colId: 'manipulation' },
        next_node: { name: 'Next Node', colId: 'next_node', format: routeTarget },
    };
}

/**
 * What a restore does to the rows of a Decision Table grid (Changes tab of a version preview); `null` when the node
 * shows no field marks or no row is marked. `groups` are the version's, as the panel holds them; `nodeIdOfKey` finds
 * the canvas node a removed group routes to; `routeTarget` names the node a route value (a match key) leads to, as
 * the Next Node cell shows it.
 */
export function decisionTableRowChanges(
    diff: UnionNodeDiffState | null,
    groups: readonly ConditionGroup[],
    nodeIdOfKey: (key: string) => string | null,
    routeTarget: (value: unknown) => string
): ConditionGroupGridRowChanges | null {
    return conditionGroupGridRowChanges(
        NodeType.TABLE,
        diff,
        groups,
        decisionTableColumns(routeTarget),
        ({ name, group, rowNumber }): RemovedGroupRow => {
            const nextNode = group['next_node'];
            const position = group['position'];
            return removedGroupRow({
                // As the canvas grid shows it: it trims the names it loads.
                group_name: name.trim(),
                group_type: group['group_type'] === 'simple' ? 'simple' : 'complex',
                expression: textOrNull(group['expression']),
                conditions: Array.isArray(group['conditions']) ? (group['conditions'] as Condition[]) : [],
                manipulation: textOrNull(group['manipulation']),
                next_node: typeof nextNode === 'string' ? nodeIdOfKey(nextNode) : null,
                // Its number on the canvas grid, as the row number column shows it.
                order: rowNumber ?? (typeof position === 'number' ? position : undefined),
            });
        }
    );
}

function textOrNull(value: unknown): string | null {
    return typeof value === 'string' ? value : null;
}
