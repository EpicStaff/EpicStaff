import { NodeType } from '@shared/models';

import { ConditionGroup } from '../../../../core/models/decision-table.model';
import { cellTooltipOf, rowMarkOf } from '../../shared/condition-group-row-marks/condition-group-row-marks';
import {
    cellTooltipText,
    conditionGroupsDiff,
} from '../../shared/condition-group-row-marks/condition-group-row-marks.testing';
import { decisionTableRowChanges } from './decision-table-row-changes';

// What a restore does to the rows of a Decision Table grid, from the real diff of both sides. The grid numbers every
// row (`#`), an invalid one too, while the diff leaves invalid groups out: a canvas place is said by the grid's number.

function group(name: string, order: number, overrides: Partial<ConditionGroup> = {}): ConditionGroup {
    return {
        group_name: name,
        group_type: 'complex',
        expression: 'x > 0',
        conditions: [],
        manipulation: null,
        next_node: null,
        order,
        ...overrides,
    };
}

/** An unfinished row the canvas grid shows first: never saved, so the diff leaves it out. */
const DRAFT = group('', 1, { expression: null, valid: false });

/** How the panel names the node a route leads to; the fixture's node references are their own match keys. */
const routeTarget = (value: unknown): string => `Node ${String(value)}`;

describe('decisionTableRowChanges', () => {
    it('names the canvas place of a moved group by the row number the canvas grid shows', () => {
        const version = [group('b', 1), group('a', 2)];

        const changes = decisionTableRowChanges(
            conditionGroupsDiff(NodeType.TABLE, [DRAFT, group('a', 2), group('b', 3)], version),
            version,
            () => null,
            routeTarget
        );

        expect(rowMarkOf(changes, version[0])?.hint).toBe('Moved (current canvas: position 3).');
    });

    it('numbers a removed group by its canvas grid row and names it as that grid shows it, trimmed', () => {
        const version = [group('a', 1)];

        const changes = decisionTableRowChanges(
            conditionGroupsDiff(NodeType.TABLE, [DRAFT, group('a', 2), group(' gone ', 3)], version),
            version,
            () => null,
            routeTarget
        );

        expect(changes?.removed.map(({ group_name, order }) => ({ group_name, order }))).toEqual([
            { group_name: 'gone', order: 3 },
        ]);
    });
});

describe('decisionTableRowChanges: the tooltip over each cell of a changed row', () => {
    const CANVAS = group('yes', 1, {
        expression: 'x > 1',
        manipulation: 'y = 1',
        next_node: 'node-a',
        conditions: [{ condition_name: 'c', condition: 'x > 1' }],
    });

    it.each<{ case: string; version: Partial<ConditionGroup>; tooltips: Record<string, string> }>([
        {
            case: 'a changed expression: its current value, the replaced part struck',
            version: { expression: 'x > 9' },
            tooltips: { expression: 'x > ~~1~~', manipulation: 'Changed columns: Expression.' },
        },
        {
            case: 'a changed manipulation',
            version: { manipulation: 'y = 2' },
            tooltips: { manipulation: 'y = ~~1~~', expression: 'Changed columns: Manipulation.' },
        },
        {
            case: 'a manipulation the version does not have: the whole current value struck',
            version: { manipulation: null },
            tooltips: { manipulation: '~~y = 1~~' },
        },
        {
            case: 'a changed route: the node the canvas routes to, by name, struck whole',
            version: { next_node: 'node-b' },
            tooltips: { next_node: '~~Node node-a~~', expression: 'Changed columns: Next Node.' },
        },
        {
            case: 'changed conditions and group type: no column of their own, the summary on every cell',
            version: { group_type: 'simple', conditions: [] },
            tooltips: {
                expression: 'Changed columns: Group type, Conditions.',
                next_node: 'Changed columns: Group type, Conditions.',
            },
        },
        {
            case: 'the name and number cells always show the summary',
            version: { expression: 'x > 9' },
            tooltips: { group_name: 'Changed columns: Expression.', index: 'Changed columns: Expression.' },
        },
    ])('$case', ({ version: versionFields, tooltips }) => {
        const version = [group('yes', 1, { ...CANVAS, ...versionFields })];
        const changes = decisionTableRowChanges(
            conditionGroupsDiff(NodeType.TABLE, [CANVAS], version),
            version,
            () => null,
            routeTarget
        );

        const shown = Object.fromEntries(
            Object.keys(tooltips).map((colId) => [colId, cellTooltipText(cellTooltipOf(changes, version[0], colId))])
        );
        expect(shown).toEqual(tooltips);
    });

    it('shows no cell tooltip on a row a restore adds', () => {
        const version = [CANVAS, group('new', 2)];
        const changes = decisionTableRowChanges(
            conditionGroupsDiff(NodeType.TABLE, [CANVAS], version),
            version,
            () => null,
            routeTarget
        );

        expect(rowMarkOf(changes, version[1])?.status).toBe('added');
        expect(cellTooltipOf(changes, version[1], 'expression')).toBeNull();
    });
});
