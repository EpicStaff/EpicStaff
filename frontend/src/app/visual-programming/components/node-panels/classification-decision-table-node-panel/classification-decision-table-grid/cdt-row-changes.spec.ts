import { NodeType } from '@shared/models';

import { CdtSection } from '../../../../core/models/cdt-section.model';
import { ConditionGroup } from '../../../../core/models/decision-table.model';
import {
    cellTooltipOf,
    ConditionGroupGridRowChanges,
    removedGroupRow,
    rowMarkOf,
} from '../../shared/condition-group-row-marks/condition-group-row-marks';
import {
    cellTooltipText,
    conditionGroupsDiff,
} from '../../shared/condition-group-row-marks/condition-group-row-marks.testing';
import { cdtRowChanges, withRemovedRows } from './cdt-row-changes';

// What a restore does to the rows of a Classification Decision Table grid, from the real diff of both sides. Rule names
// may repeat in this table: each rule is matched to its own change, never by its name.

const BILLING: CdtSection = { id: 'section-billing', name: 'Billing', metadata: {} };

function rule(name: string, order: number, overrides: Partial<ConditionGroup> = {}): ConditionGroup {
    return {
        group_name: name,
        group_type: 'simple',
        expression: `x > ${order}`,
        conditions: [],
        manipulation: null,
        next_node: null,
        route_code: null,
        continue_flag: false,
        dock_visible: true,
        order,
        ...overrides,
    };
}

function rowChangesOf(canvas: ConditionGroup[], version: ConditionGroup[]): ConditionGroupGridRowChanges | null {
    return cdtRowChanges(conditionGroupsDiff(NodeType.CLASSIFICATION_TABLE, canvas, version), version, [], () => null);
}

describe('cdtRowChanges: rules with the same name', () => {
    it.each<{ case: string; canvas: ConditionGroup[]; version: ConditionGroup[]; marks: (string | null)[] }>([
        {
            case: 'a change of the second marks the second only',
            canvas: [rule('Rule', 1), rule('Rule', 2)],
            version: [rule('Rule', 1), rule('Rule', 2, { expression: 'x > 9' })],
            marks: [null, 'changed'],
        },
        {
            case: 'a change of the first marks the first only',
            canvas: [rule('Rule', 1), rule('Rule', 2)],
            version: [rule('Rule', 1, { expression: 'x > 9' }), rule('Rule', 2)],
            marks: ['changed', null],
        },
        {
            case: 'a second one a restore adds is marked added, the first is kept',
            canvas: [rule('Rule', 1)],
            version: [rule('Rule', 1), rule('Rule', 2)],
            marks: [null, 'added'],
        },
        {
            case: 'both kept while another rule changes: neither is marked',
            canvas: [rule('Rule', 1), rule('Rule', 2), rule('Other', 3)],
            version: [rule('Rule', 1), rule('Rule', 2), rule('Other', 3, { expression: 'x > 9' })],
            marks: [null, null, 'changed'],
        },
    ])('$case', ({ canvas, version, marks }) => {
        const changes = rowChangesOf(canvas, version);

        expect(version.map((group) => rowMarkOf(changes, group)?.status ?? null)).toEqual(marks);
    });

    it('lists the changed columns of the second in its own tooltip', () => {
        const version = [rule('Rule', 1), rule('Rule', 2, { expression: 'x > 9' })];

        expect(rowMarkOf(rowChangesOf([rule('Rule', 1), rule('Rule', 2)], version), version[1])?.hint).toBe(
            'Changed columns: Expression.'
        );
    });

    it('shows a second rule a restore removes by its real name', () => {
        const version = [rule('Rule', 1)];
        const changes = rowChangesOf([rule('Rule', 1), rule('Rule', 2, { expression: 'x < 0' })], version);

        expect(changes?.removed.map(({ group_name, expression }) => ({ group_name, expression }))).toEqual([
            { group_name: 'Rule', expression: 'x < 0' },
        ]);
        expect(rowMarkOf(changes, version[0])).toBeNull();
    });
});

describe('withRemovedRows', () => {
    const rows = [rule('invoice', 1, { section: BILLING.id }), rule('other', 2)];

    it('puts a removed rule after the last rule of its section, and one without a section last', () => {
        const shown = withRemovedRows(rows, [
            removedGroupRow(rule('chargeback', 2, { section: BILLING.id })),
            removedGroupRow(rule('legacy', 3)),
        ]);

        expect(shown.map(({ group_name, section }) => ({ group_name, section: section ?? null }))).toEqual([
            { group_name: 'invoice', section: BILLING.id },
            { group_name: 'chargeback', section: BILLING.id },
            { group_name: 'other', section: null },
            { group_name: 'legacy', section: null },
        ]);
    });

    it('puts a removed rule whose section has no rules left last, out of that section, so no fold can hide it', () => {
        const shown = withRemovedRows(rows, [removedGroupRow(rule('lost', 3, { section: 'section-emptied' }))]);

        expect(shown.at(-1)).toMatchObject({ group_name: 'lost', section: null, removedByRestore: true });
    });
});

describe('cdtRowChanges: the tooltip over each cell of a changed rule', () => {
    const CANVAS = rule('invoice', 1, {
        expression: 'variables.total > 1',
        manipulation: 'variables.total = 1',
        prompt_id: 'classify',
        route_code: 'A',
        next_node: 'node-a',
        field_expressions: { amount: '> 1', city: '== "Kyiv"' },
        field_manipulations: { total: 'variables.total + 1', note: '"paid"' },
    });

    it.each<{ case: string; version: Partial<ConditionGroup>; tooltips: Record<string, string> }>([
        {
            case: 'a changed expression, its variables as the cell shows them',
            version: { expression: 'variables.total > 9' },
            tooltips: { expression: '@total > ~~1~~' },
        },
        {
            case: 'a changed field expression: that field’s own value; a field kept shows the summary',
            version: { field_expressions: { amount: '> 2', city: '== "Kyiv"' } },
            tooltips: { field_amount: '> ~~1~~', field_city: 'Changed columns: amount.' },
        },
        {
            case: 'a changed manipulation',
            version: { manipulation: 'variables.total = 2' },
            tooltips: { manipulation: '@total = ~~1~~' },
        },
        {
            case: 'a changed field manipulation: that field’s own value; a field kept shows the summary',
            version: { field_manipulations: { total: 'variables.total + 2', note: '"paid"' } },
            tooltips: { manip_total: '@total + ~~1~~', manip_note: 'Changed columns: total.' },
        },
        {
            case: 'a changed prompt',
            version: { prompt_id: 'triage' },
            tooltips: { prompt_id: '~~classify~~' },
        },
        { case: 'a changed route code', version: { route_code: 'B' }, tooltips: { route_code: '~~A~~' } },
        { case: 'Continue turned on', version: { continue_flag: true }, tooltips: { continue_flag: '~~off~~' } },
        { case: 'the route port hidden', version: { dock_visible: false }, tooltips: { dock_visible: '~~on~~' } },
        {
            case: 'a changed route target: no column of its own, the summary on every cell',
            version: { next_node: 'node-b' },
            tooltips: { route_code: 'Changed columns: Next Node.', expression: 'Changed columns: Next Node.' },
        },
    ])('$case', ({ version: versionFields, tooltips }) => {
        const version = [rule('invoice', 1, { ...CANVAS, ...versionFields })];
        const changes = rowChangesOf([CANVAS], version);

        const shown = Object.fromEntries(
            Object.keys(tooltips).map((colId) => [colId, cellTooltipText(cellTooltipOf(changes, version[0], colId))])
        );
        expect(shown).toEqual(tooltips);
    });
});
