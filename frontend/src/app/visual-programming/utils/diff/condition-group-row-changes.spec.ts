import {
    ConditionGroupRowChanges,
    conditionGroupRowChanges,
    GroupFieldColumns,
    movedKeys,
} from './condition-group-row-changes';
import { diffProjections } from './diff-fields';
import { DisplaySegment } from './field-change-display';
import { NodeDiffStatus } from './types';

describe('movedKeys', () => {
    it.each<{ case: string; current: string[]; version: string[]; moved: string[] }>([
        { case: 'same order', current: ['a', 'b', 'c'], version: ['a', 'b', 'c'], moved: [] },
        {
            case: 'swap of two neighbours: the one moved up',
            current: ['a', 'b', 'c'],
            version: ['b', 'a', 'c'],
            moved: ['b'],
        },
        { case: 'swap of the last two', current: ['a', 'b', 'c'], version: ['a', 'c', 'b'], moved: ['c'] },
        { case: 'move to the top', current: ['a', 'b', 'c', 'd'], version: ['d', 'a', 'b', 'c'], moved: ['d'] },
        { case: 'move to the bottom', current: ['a', 'b', 'c', 'd'], version: ['b', 'c', 'd', 'a'], moved: ['a'] },
        { case: 'add at the top: a shift, no move', current: ['a', 'b'], version: ['x', 'a', 'b'], moved: [] },
        { case: 'remove at the top: a shift, no move', current: ['x', 'a', 'b'], version: ['a', 'b'], moved: [] },
        { case: 'remove one and move another', current: ['a', 'b', 'c', 'd'], version: ['c', 'a', 'd'], moved: ['c'] },
        { case: 'add one and move another', current: ['a', 'b', 'c'], version: ['c', 'x', 'a', 'b'], moved: ['c'] },
        { case: 'reversed: all but one moved', current: ['a', 'b', 'c'], version: ['c', 'b', 'a'], moved: ['c', 'b'] },
        { case: 'nothing shared', current: ['a'], version: ['b'], moved: [] },
        { case: 'empty', current: [], version: [], moved: [] },
    ])('$case', ({ current, version, moved }) => {
        expect([...movedKeys(current, version)].sort()).toEqual([...moved].sort());
    });
});

/** Segments as one text, the struck parts in `~~`: `x > ~~1~~`. */
function struckText(segments: readonly DisplaySegment[] | undefined): string | undefined {
    return segments?.map(({ text, struck }) => (struck ? `~~${text}~~` : text)).join('');
}

describe('conditionGroupRowChanges', () => {
    const COLUMNS: GroupFieldColumns = {
        group_type: { name: 'Group type' },
        expression: { name: 'Expression', colId: 'expression' },
        field_expressions: {
            colIdOfKey: (field) => `field_${field}`,
            shownText: (text) => text.replace('vars.', '@'),
        },
        manipulation: { name: 'Manipulation', colId: 'manipulation', shownText: (text) => text.replace('vars.', '@') },
        next_node: { name: 'Next Node', colId: 'next_node', format: (value) => `Node ${String(value)}` },
    };

    type Group = Record<string, unknown>;
    const group = (position: number, fields: Group = {}): Group => ({
        position,
        expression: 'x > 1',
        field_expressions: {},
        manipulation: null,
        next_node: null,
        ...fields,
    });

    /** The groups of both sides by name, in order; the diff is the real one between them. */
    function rowChangesOf(
        current: Record<string, Group>,
        version: Record<string, Group>,
        status: NodeDiffStatus = 'changed'
    ): ConditionGroupRowChanges | null {
        const fields = diffProjections({ condition_groups: current }, { condition_groups: version });
        return conditionGroupRowChanges({ status, fields, missingReferences: [] }, Object.keys(version), COLUMNS);
    }

    const hints = (changes: ConditionGroupRowChanges | null): Record<string, string | null> =>
        Object.fromEntries([...(changes?.rows ?? new Map())].map(([name, mark]) => [name, mark.hint]));

    it('names the changed columns of a row in the grid order, each once', () => {
        const changes = rowChangesOf(
            { yes: group(1, { next_node: 'uuid:a', expression: 'x > 1' }) },
            { yes: group(1, { next_node: 'uuid:b', expression: 'x > 2' }) }
        );

        expect(changes?.rows.get('yes')).toMatchObject({
            status: 'changed',
            hint: 'Changed columns: Expression, Next Node.',
        });
        expect(changes?.removed).toEqual([]);
    });

    it.each<{ case: string; current: unknown; version: unknown; hint: string }>([
        {
            case: 'one key changed',
            current: { a: '> 1', b: '' },
            version: { a: '> 2', b: '' },
            hint: 'Changed columns: a.',
        },
        { case: 'a key only the version has', current: {}, version: { a: '> 1' }, hint: 'Changed columns: a.' },
        {
            case: 'a key only the canvas has, after the version keys',
            current: { z: '1', a: '1' },
            version: { a: '2' },
            hint: 'Changed columns: a, z.',
        },
    ])('names the field columns of a map by key: $case', ({ current, version, hint }) => {
        const changes = rowChangesOf(
            { yes: group(1, { field_expressions: current }) },
            { yes: group(1, { field_expressions: version }) }
        );

        expect(hints(changes)).toEqual({ yes: hint });
    });

    it('marks a group only the version has as added, with no tooltip', () => {
        const changes = rowChangesOf({ yes: group(1) }, { yes: group(1), no: group(2) });

        expect(changes?.rows.get('no')).toEqual({ status: 'added', hint: null, cells: new Map() });
        expect(changes?.rows.has('yes')).toBe(false);
    });

    it('gives the groups only the canvas has in their canvas order, as the diff compares them', () => {
        const changes = rowChangesOf(
            { late: group(3, { expression: 'late' }), yes: group(1), early: group(2, { expression: 'early' }) },
            { yes: group(1) }
        );

        expect(changes?.removed).toEqual([
            { key: 'early', group: group(2, { expression: 'early' }) },
            { key: 'late', group: group(3, { expression: 'late' }) },
        ]);
        expect(changes?.rows.size).toBe(0);
    });

    it('does not mark the groups shifted by a group a restore adds or removes', () => {
        const added = rowChangesOf({ a: group(1), b: group(2) }, { x: group(1), a: group(2), b: group(3) });
        const removed = rowChangesOf({ x: group(1), a: group(2), b: group(3) }, { a: group(1), b: group(2) });

        expect(hints(added)).toEqual({ x: null });
        expect(hints(removed)).toEqual({});
        expect(removed?.removed.map(({ key }) => key)).toEqual(['x']);
    });

    it('names the canvas position of a moved group after its changed columns', () => {
        const changes = rowChangesOf(
            { a: group(1), b: group(2), c: group(3, { expression: 'old' }) },
            { c: group(1, { expression: 'new' }), a: group(2), b: group(3) }
        );

        expect(hints(changes)).toEqual({ c: 'Changed columns: Expression. Moved (current canvas: position 3).' });
    });

    it('marks only the group moved up in a swap', () => {
        expect(hints(rowChangesOf({ a: group(1), b: group(2) }, { b: group(1), a: group(2) }))).toEqual({
            b: 'Moved (current canvas: position 2).',
        });
    });

    it('marks a move next to a removed group by the canvas position', () => {
        const changes = rowChangesOf(
            { a: group(1), b: group(2), c: group(3), d: group(4) },
            { c: group(1), a: group(2), d: group(3) }
        );

        expect(hints(changes)).toEqual({ c: 'Moved (current canvas: position 3).' });
        expect(changes?.removed.map(({ key }) => key)).toEqual(['b']);
    });

    describe('the tooltip of each changed cell, by column id', () => {
        it.each<{ case: string; current: Group; version: Group; cells: Record<string, string> }>([
            {
                case: 'a text column: the replaced part struck',
                current: { expression: 'x > 1' },
                version: { expression: 'x > 2' },
                cells: { expression: 'x > ~~1~~' },
            },
            {
                case: 'a text column shown otherwise than stored: the shown text compared',
                current: { manipulation: 'vars.total = 1' },
                version: { manipulation: 'vars.total = 2' },
                cells: { manipulation: '@total = ~~1~~' },
            },
            {
                case: 'a column with a format: the formatted value struck whole',
                current: { next_node: 'a' },
                version: { next_node: 'b' },
                cells: { next_node: '~~Node a~~' },
            },
            {
                case: 'an empty current value',
                current: { manipulation: null },
                version: { manipulation: 'vars.total = 2' },
                cells: { manipulation: '~~empty~~' },
            },
            {
                case: 'a map: one cell per changed key, its own value, shown as the cell shows it',
                current: { field_expressions: { amount: 'vars.amount > 1', city: '== "x"', gone: '< 0' } },
                version: { field_expressions: { amount: 'vars.amount > 2', city: '== "x"', added: '> 0' } },
                cells: { field_amount: '@amount > ~~1~~', field_added: '~~empty~~', field_gone: '~~< 0~~' },
            },
            {
                case: 'a field no column shows: named in the summary only',
                current: { group_type: 'simple', expression: 'x > 1' },
                version: { group_type: 'complex', expression: 'x > 1' },
                cells: {},
            },
        ])('$case', ({ current, version, cells }) => {
            const mark = rowChangesOf({ yes: group(1, current) }, { yes: group(1, version) })?.rows.get('yes');

            expect(
                Object.fromEntries([...(mark?.cells ?? [])].map(([id, segments]) => [id, struckText(segments)]))
            ).toEqual(cells);
        });

        it('gives a moved row no cell tooltip for its position', () => {
            const mark = rowChangesOf({ a: group(1), b: group(2) }, { b: group(1), a: group(2) })?.rows.get('b');

            expect(mark?.hint).toBe('Moved (current canvas: position 2).');
            expect(mark?.cells.size).toBe(0);
        });
    });

    it('marks nothing for a field the grid does not name', () => {
        expect(
            rowChangesOf({ yes: group(1, { dock_visible: true }) }, { yes: group(1, { dock_visible: false }) })
        ).toBeNull();
    });

    it.each<NodeDiffStatus>(['added', 'deleted', 'unchanged'])('marks no row of a node a restore %s', (status) => {
        expect(
            rowChangesOf({ yes: group(1, { expression: 'a' }) }, { yes: group(1, { expression: 'b' }) }, status)
        ).toBeNull();
    });

    it('marks nothing off the Changes tab or when no group changed', () => {
        expect(conditionGroupRowChanges(null, ['yes'], COLUMNS)).toBeNull();
        expect(rowChangesOf({ yes: group(1) }, { yes: group(1) })).toBeNull();
    });
});
