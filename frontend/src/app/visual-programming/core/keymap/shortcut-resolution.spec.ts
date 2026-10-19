import { CustomShortcutEntry, ShortcutParams } from '@shared/models';

import { EditorActionId } from './editor-actions';
import { KeyChord } from './key-chord.util';
import {
    applyShortcutChange,
    CustomShortcutRow,
    haveSameEntries,
    identifyRows,
    readCustomEntries,
    resolveShortcuts,
    ShortcutChange,
    ShortcutChangeResult,
    toShortcutSettings,
} from './shortcut-resolution';

function rows(...entries: readonly (readonly [string, KeyChord | null])[]): CustomShortcutRow[] {
    return entries.map(([action, chord], index) => ({ id: `row-${index}`, action, chord }));
}

const NO_ROWS = rows();

function bindingsOf(value: readonly CustomShortcutRow[]): Record<string, readonly KeyChord[]> {
    return Object.fromEntries(resolveShortcuts(value).bindings);
}

function rowsAfter(result: ShortcutChangeResult): readonly CustomShortcutRow[] {
    if (!result.accepted) throw new Error(`change was rejected: ${result.rejection}`);
    return result.rows;
}

function entriesOf(value: readonly CustomShortcutRow[]): [string, KeyChord | null][] {
    return value.map((row) => [row.action, row.chord]);
}

describe('resolveShortcuts', () => {
    it('gives every action its default keys when there are no custom shortcuts', () => {
        const resolved = resolveShortcuts(NO_ROWS);

        expect(resolved.bindings.get('node.python')).toEqual(['Shift+KeyP']);
        expect(resolved.bindings.get('editing.redo')).toEqual(['Mod+Shift+KeyZ', 'Mod+KeyY']);
        expect(resolved.bindings.get('zoom.in')).toEqual([]);
        expect(resolved.customShortcuts).toEqual([]);
        expect([...resolved.unboundIds]).toEqual([]);
    });

    it.each<[string, readonly CustomShortcutRow[], EditorActionId, KeyChord[], KeyChord[]]>([
        [
            'a custom key is added after the base key',
            rows(['node.python', 'Alt+KeyQ']),
            'node.python',
            ['Shift+KeyP', 'Alt+KeyQ'],
            ['Shift+KeyP'],
        ],
        [
            'an editor action keeps its defaults and gains the custom key',
            rows(['editing.save', 'Alt+KeyS']),
            'editing.save',
            ['Mod+KeyS', 'Alt+KeyS'],
            ['Mod+KeyS'],
        ],
        [
            'a custom key takes another node base key: that node loses it',
            rows(['node.task', 'Shift+KeyP']),
            'node.python',
            [],
            [],
        ],
        [
            'the action of the custom row holds the taken key',
            rows(['node.task', 'Shift+KeyP']),
            'node.task',
            ['Shift+KeyT', 'Shift+KeyP'],
            ['Shift+KeyT'],
        ],
        [
            'a custom row without a key adds nothing',
            rows(['node.task', null]),
            'node.task',
            ['Shift+KeyT'],
            ['Shift+KeyT'],
        ],
    ])('custom wins over a node base key: %s', (_case, value, actionId, bindings, builtIn) => {
        const resolved = resolveShortcuts(value);

        expect(resolved.bindings.get(actionId)).toEqual(bindings);
        expect(resolved.builtInBindings.get(actionId)).toEqual(builtIn);
    });

    it.each<[string, readonly CustomShortcutRow[], EditorActionId[]]>([
        ['nothing', NO_ROWS, []],
        ['a node whose base key a custom row took', rows(['editing.save', 'Shift+KeyP']), ['node.python']],
        ['two nodes', rows(['node.task', 'Shift+KeyP'], ['node.agent', 'Shift+KeyT']), ['node.python', 'node.task']],
        ['a custom row without a key', rows(['node.task', null], ['node.agent', null]), []],
    ])('lists the nodes left without a base key for %s', (_case, value, expected) => {
        expect([...resolveShortcuts(value).unboundIds].sort()).toEqual([...expected].sort());
    });

    it.each<[string, readonly CustomShortcutRow[], KeyChord, EditorActionId | null, string | null]>([
        ['a base key', NO_ROWS, 'Shift+KeyP', 'node.python', null],
        ['a custom key', rows(['editing.save', 'Alt+KeyS']), 'Alt+KeyS', 'editing.save', 'row-0'],
        ['a node key a custom row took', rows(['node.task', 'Shift+KeyP']), 'Shift+KeyP', 'node.task', 'row-0'],
        ['nobody', NO_ROWS, 'Alt+KeyQ', null, null],
    ])('names who holds %s', (_case, value, chord, action, rowId) => {
        const holder = resolveShortcuts(value).holders.get(chord);

        expect(holder?.action ?? null).toBe(action);
        expect(holder?.customShortcutId ?? null).toBe(rowId);
    });

    it.each<[string, readonly CustomShortcutRow[]]>([
        ['an unknown action', rows(['gone.action', 'Alt+KeyQ'])],
        ['Escape, which takes no custom keys', rows(['editing.escape', 'Alt+KeyE'])],
        ['a gesture row', rows(['zoom.in', 'Alt+KeyI'])],
    ])('drops a stored row for %s and keeps every default', (_case, value) => {
        const resolved = resolveShortcuts(value);

        expect(Object.fromEntries(resolved.bindings)).toEqual(bindingsOf(NO_ROWS));
        expect(resolved.customShortcuts).toEqual([]);
    });

    it.each<[string, readonly CustomShortcutRow[]]>([
        ['a reserved chord', rows(['node.agent', 'Mod+KeyW'])],
        ['another action default', rows(['node.agent', 'Mod+KeyV'])],
        ['the action own default', rows(['node.python', 'Shift+KeyP'])],
        ['a malformed chord', rows(['node.agent', 'Shift+'])],
        ['a bare key', rows(['node.agent', 'KeyQ'])],
        ['a mac Ctrl chord', rows(['node.agent', 'Ctrl+KeyQ'])],
    ])('keeps a stored row with %s without a key and keeps every default', (_case, value) => {
        const resolved = resolveShortcuts(value);

        expect(Object.fromEntries(resolved.bindings)).toEqual(bindingsOf(NO_ROWS));
        expect(resolved.customShortcuts).toEqual([{ id: 'row-0', action: value[0].action, chord: null }]);
    });

    it('gives a key two rows share to the first and keeps the second without a key', () => {
        const resolved = resolveShortcuts(
            rows(['node.task', 'Alt+KeyQ'], ['node.agent', 'Alt+KeyQ'], ['editing.save', null], ['editing.undo', null])
        );

        expect(resolved.customShortcuts).toEqual([
            { id: 'row-0', action: 'node.task', chord: 'Alt+KeyQ' },
            { id: 'row-1', action: 'node.agent', chord: null },
            { id: 'row-2', action: 'editing.save', chord: null },
            { id: 'row-3', action: 'editing.undo', chord: null },
        ]);
    });

    it.each<[string, readonly CustomShortcutRow[], number]>([
        ['nothing to reset', rows(['editing.save', 'Alt+KeyS'], ['node.task', null]), 0],
        [
            'two rows holding node base keys',
            rows(['node.task', 'Shift+KeyP'], ['editing.save', 'Alt+KeyS'], ['editing.undo', 'Shift+KeyA']),
            2,
        ],
    ])('counts the rows a reset to defaults would clear with %s', (_case, value, expected) => {
        expect(resolveShortcuts(value).defaultsResetClearCount).toBe(expected);
    });
});

describe('readCustomEntries', () => {
    it.each<[string, unknown, [string, KeyChord | null][]]>([
        [
            'the custom list',
            {
                custom: [
                    { action: 'node.task', keys: 'Alt+KeyT' },
                    { action: 'editing.save', keys: null },
                ],
            },
            [
                ['node.task', 'Alt+KeyT'],
                ['editing.save', null],
            ],
        ],
        [
            'entries of the wrong shape',
            { custom: ['Alt+KeyQ', null, { action: 'node.agent' }, { action: 'node.agent', keys: 5 }] },
            [],
        ],
        ['a value from before the custom list', { 'node.agent': 'Shift+KeyB' }, []],
        ['an empty object', {}, []],
        ['null', null, []],
    ])('reads %s without crashing', (_case, value, expected) => {
        expect(readCustomEntries(value).map((entry) => [entry.action, entry.keys])).toEqual(expected);
    });
});

describe('identifyRows', () => {
    it('keeps the id of every row that is still there and gives new rows new ids', () => {
        const previous = rows(['node.task', 'Alt+KeyT'], ['editing.save', 'Alt+KeyS'], ['editing.undo', null]);
        let created = 0;

        const identified = identifyRows(
            [
                { action: 'editing.save', keys: 'Alt+KeyS' },
                { action: 'editing.save', keys: 'Alt+KeyD' },
                { action: 'editing.undo', keys: null },
            ],
            previous,
            () => `new-${++created}`
        );

        expect(identified.map((row) => row.id)).toEqual(['row-1', 'new-1', 'row-2']);
    });
});

describe('applyShortcutChange', () => {
    it.each<
        [
            string,
            readonly CustomShortcutRow[],
            ShortcutChange,
            string,
            { action: EditorActionId; customShortcutId: string | null } | null,
        ]
    >([
        [
            'a reserved chord',
            NO_ROWS,
            { kind: 'add-custom', id: 'new', action: 'node.agent', chord: 'Mod+KeyW' },
            'reserved',
            null,
        ],
        [
            'another editor action default',
            NO_ROWS,
            { kind: 'add-custom', id: 'new', action: 'node.agent', chord: 'Mod+KeyC' },
            'reserved',
            null,
        ],
        [
            'Backspace',
            NO_ROWS,
            { kind: 'add-custom', id: 'new', action: 'editing.save', chord: 'Backspace' },
            'reserved',
            null,
        ],
        [
            'Escape',
            NO_ROWS,
            { kind: 'add-custom', id: 'new', action: 'editing.save', chord: 'Escape' },
            'reserved',
            null,
        ],
        [
            'Ctrl+/',
            NO_ROWS,
            { kind: 'add-custom', id: 'new', action: 'node.agent', chord: 'Mod+Slash' },
            'reserved',
            null,
        ],
        [
            'a bare key',
            NO_ROWS,
            { kind: 'add-custom', id: 'new', action: 'editing.save', chord: 'F2' },
            'bare-key',
            null,
        ],
        [
            'a mac Ctrl chord',
            NO_ROWS,
            { kind: 'add-custom', id: 'new', action: 'editing.save', chord: 'Ctrl+KeyS' },
            'mac-ctrl',
            null,
        ],
        [
            'a malformed chord',
            NO_ROWS,
            { kind: 'add-custom', id: 'new', action: 'editing.save', chord: 'Shift+' },
            'invalid',
            null,
        ],
        [
            'the editor action own default',
            NO_ROWS,
            { kind: 'add-custom', id: 'new', action: 'editing.redo', chord: 'Mod+KeyY' },
            'taken',
            { action: 'editing.redo', customShortcutId: null },
        ],
        [
            'the node action own base key',
            NO_ROWS,
            { kind: 'add-custom', id: 'new', action: 'node.python', chord: 'Shift+KeyP' },
            'taken',
            { action: 'node.python', customShortcutId: null },
        ],
        [
            'a key another custom row holds',
            rows(['editing.save', 'Alt+KeyS']),
            { kind: 'add-custom', id: 'new', action: 'node.agent', chord: 'Alt+KeyS' },
            'taken',
            { action: 'editing.save', customShortcutId: 'row-0' },
        ],
        [
            'an edit onto a key another custom row holds',
            rows(['editing.save', 'Alt+KeyS'], ['editing.undo', 'Alt+KeyU']),
            { kind: 'update-custom', id: 'row-0', action: 'editing.save', chord: 'Alt+KeyU' },
            'taken',
            { action: 'editing.undo', customShortcutId: 'row-1' },
        ],
        [
            'an edit of a row that no longer exists',
            rows(['editing.save', 'Alt+KeyS']),
            { kind: 'update-custom', id: 'gone', action: 'editing.save', chord: 'Alt+KeyD' },
            'missing',
            null,
        ],
        [
            'a removal of a row that no longer exists',
            rows(['editing.save', 'Alt+KeyS']),
            { kind: 'remove-custom', id: 'gone' },
            'missing',
            null,
        ],
    ])('rejects %s', (_case, value, change, rejection, takenBy) => {
        expect(applyShortcutChange(value, change)).toMatchObject({ accepted: false, rejection, takenBy });
    });

    it.each<[string, readonly CustomShortcutRow[], ShortcutChange, EditorActionId | null, [string, KeyChord | null][]]>(
        [
            [
                'a free key, appended',
                rows(['node.task', 'Alt+KeyT']),
                { kind: 'add-custom', id: 'new', action: 'editing.undo', chord: 'Alt+KeyU' },
                null,
                [
                    ['node.task', 'Alt+KeyT'],
                    ['editing.undo', 'Alt+KeyU'],
                ],
            ],
            [
                'a node base key, taken from that node',
                NO_ROWS,
                { kind: 'add-custom', id: 'new', action: 'editing.save', chord: 'Shift+KeyP' },
                'node.python',
                [['editing.save', 'Shift+KeyP']],
            ],
            [
                'a row without a key',
                rows(['editing.save', null]),
                { kind: 'add-custom', id: 'new', action: 'editing.undo', chord: null },
                null,
                [
                    ['editing.save', null],
                    ['editing.undo', null],
                ],
            ],
            [
                'an edited key, kept in place',
                rows(['node.task', 'Alt+KeyT'], ['editing.undo', 'Alt+KeyU']),
                { kind: 'update-custom', id: 'row-0', action: 'node.task', chord: 'Shift+KeyA' },
                'node.agent',
                [
                    ['node.task', 'Shift+KeyA'],
                    ['editing.undo', 'Alt+KeyU'],
                ],
            ],
            [
                'an edited action on a key the row already took',
                rows(['node.task', 'Shift+KeyP']),
                { kind: 'update-custom', id: 'row-0', action: 'node.agent', chord: 'Shift+KeyP' },
                null,
                [['node.agent', 'Shift+KeyP']],
            ],
            [
                'an edit that clears the key',
                rows(['node.task', 'Shift+KeyP']),
                { kind: 'update-custom', id: 'row-0', action: 'node.task', chord: null },
                null,
                [['node.task', null]],
            ],
            [
                'a removed row',
                rows(['node.task', 'Shift+KeyP'], ['editing.undo', 'Alt+KeyU']),
                { kind: 'remove-custom', id: 'row-0' },
                null,
                [['editing.undo', 'Alt+KeyU']],
            ],
            [
                'a reset to defaults: rows on node base keys lose their keys, unique keys stay',
                rows(
                    ['node.task', 'Shift+KeyP'],
                    ['editing.save', 'Alt+KeyS'],
                    ['editing.undo', 'Shift+KeyA'],
                    ['node.agent', null]
                ),
                { kind: 'reset-to-defaults' },
                null,
                [
                    ['node.task', null],
                    ['editing.save', 'Alt+KeyS'],
                    ['editing.undo', null],
                    ['node.agent', null],
                ],
            ],
        ]
    )('accepts %s', (_case, value, change, displaces, expected) => {
        const result = applyShortcutChange(value, change);

        expect(result).toMatchObject({ accepted: true, displaces });
        expect(entriesOf(rowsAfter(result))).toEqual(expected);
    });

    it('keeps row ids through an edit and gives an added row the id it was given', () => {
        const edited = rowsAfter(
            applyShortcutChange(rows(['node.task', 'Alt+KeyT']), {
                kind: 'update-custom',
                id: 'row-0',
                action: 'editing.save',
                chord: 'Alt+KeyS',
            })
        );
        const added = rowsAfter(
            applyShortcutChange(edited, { kind: 'add-custom', id: 'added', action: 'editing.undo', chord: null })
        );

        expect(added.map((row) => row.id)).toEqual(['row-0', 'added']);
    });

    it('gives every node its base key back after a reset to defaults', () => {
        const reset = rowsAfter(
            applyShortcutChange(rows(['node.task', 'Shift+KeyP'], ['editing.undo', 'Shift+KeyA']), {
                kind: 'reset-to-defaults',
            })
        );

        expect([...resolveShortcuts(reset).unboundIds]).toEqual([]);
        expect(resolveShortcuts(reset).bindings.get('node.python')).toEqual(['Shift+KeyP']);
    });

    it('gives a node its key back when the row that took it is removed', () => {
        const next = rowsAfter(
            applyShortcutChange(rows(['node.task', 'Shift+KeyP']), { kind: 'remove-custom', id: 'row-0' })
        );

        expect(resolveShortcuts(next).bindings.get('node.python')).toEqual(['Shift+KeyP']);
    });

    it('lets a key a dropped row held go to a new row', () => {
        const next = rowsAfter(
            applyShortcutChange(rows(['action.from-a-newer-version', 'Alt+KeyN']), {
                kind: 'add-custom',
                id: 'new',
                action: 'editing.save',
                chord: 'Alt+KeyN',
            })
        );

        expect(entriesOf(next)).toEqual([['editing.save', 'Alt+KeyN']]);
    });

    it.each<[string, number, string | null]>([
        ['below the limit', 99, null],
        ['at the limit', 100, 'limit'],
    ])('adds a row %s only while under it', (_case, existing, rejection) => {
        const value = rows(...Array.from({ length: existing }, () => ['editing.save', null] as const));

        const result = applyShortcutChange(value, {
            kind: 'add-custom',
            id: 'new',
            action: 'editing.undo',
            chord: 'Alt+Digit1',
        });

        expect(result.accepted ? null : result.rejection).toBe(rejection);
    });

    it.each<[string, ShortcutChange]>([
        ['a custom key for Escape', { kind: 'add-custom', id: 'new', action: 'editing.escape', chord: 'Alt+KeyE' }],
        [
            'a custom key for a gesture row',
            { kind: 'add-custom', id: 'new', action: 'selection.zone', chord: 'Alt+KeyZ' },
        ],
    ])('refuses %s as a programming error', (_case, change) => {
        expect(() => applyShortcutChange(NO_ROWS, change)).toThrow();
    });
});

describe('shortcuts with parameters (Subgraph)', () => {
    function subgraphRow(id: string, chord: KeyChord | null, params?: ShortcutParams): CustomShortcutRow {
        return params === undefined
            ? { id, action: 'node.subgraph', chord }
            : { id, action: 'node.subgraph', chord, params };
    }

    function subgraphEntry(params: ShortcutParams | undefined): CustomShortcutEntry {
        return params === undefined
            ? { action: 'node.subgraph', keys: 'Alt+Digit1' }
            : { action: 'node.subgraph', keys: 'Alt+Digit1', params };
    }

    it('binds a Subgraph row with a flow and hands its flow to whoever holds the key', () => {
        const resolved = resolveShortcuts([subgraphRow('row-0', 'Alt+Digit1', { flowId: 12 })]);

        expect(resolved.customShortcuts).toStrictEqual([
            { id: 'row-0', action: 'node.subgraph', chord: 'Alt+Digit1', params: { flowId: 12 } },
        ]);
        expect(resolved.bindings.get('node.subgraph')).toEqual(['Alt+Digit1']);
        expect(resolved.holders.get('Alt+Digit1')?.params).toEqual({ flowId: 12 });
    });

    it('gives two Subgraph rows for different flows their own key and their own flow', () => {
        const holders = resolveShortcuts([
            subgraphRow('row-0', 'Alt+Digit1', { flowId: 12 }),
            subgraphRow('row-1', 'Alt+Digit2', { flowId: 34 }),
        ]).holders;

        expect([holders.get('Alt+Digit1')?.params, holders.get('Alt+Digit2')?.params]).toEqual([
            { flowId: 12 },
            { flowId: 34 },
        ]);
    });

    it.each<[string, ShortcutParams | undefined]>([
        ['no params', undefined],
        ['no flowId', { flow: 12 }],
        ['a flowId written as text', { flowId: '12' }],
        ['a zero flowId', { flowId: 0 }],
        ['a negative flowId', { flowId: -3 }],
        ['a fractional flowId', { flowId: 1.5 }],
    ])('keeps a Subgraph row with %s but gives it no key', (_case, params) => {
        const resolved = resolveShortcuts([subgraphRow('row-0', 'Alt+Digit1', params)]);

        expect(resolved.customShortcuts).toStrictEqual([{ id: 'row-0', action: 'node.subgraph', chord: null }]);
        expect(resolved.holders.has('Alt+Digit1')).toBe(false);
    });

    it('keeps only the flowId of a Subgraph row', () => {
        const resolved = resolveShortcuts([subgraphRow('row-0', 'Alt+Digit1', { flowId: 12, note: 'x' })]);

        expect(resolved.customShortcuts[0].params).toStrictEqual({ flowId: 12 });
    });

    it('drops params from an action that takes none', () => {
        const resolved = resolveShortcuts([
            { id: 'row-0', action: 'node.agent', chord: 'Alt+KeyB', params: { flowId: 12 } },
        ]);

        expect(resolved.customShortcuts).toStrictEqual([{ id: 'row-0', action: 'node.agent', chord: 'Alt+KeyB' }]);
        expect(resolved.holders.get('Alt+KeyB')?.params).toBeUndefined();
    });

    it.each<[string, ShortcutChange]>([
        [
            'an added Subgraph row without a flow',
            { kind: 'add-custom', id: 'new', action: 'node.subgraph', chord: 'Alt+Digit1' },
        ],
        [
            'an added Subgraph row without a flow or a key',
            { kind: 'add-custom', id: 'new', action: 'node.subgraph', chord: null },
        ],
        [
            'an added Subgraph row with a broken flow',
            { kind: 'add-custom', id: 'new', action: 'node.subgraph', chord: 'Alt+Digit1', params: { flowId: 'x' } },
        ],
        [
            'an edit that turns a row into Subgraph without a flow',
            { kind: 'update-custom', id: 'row-0', action: 'node.subgraph', chord: 'Alt+KeyB' },
        ],
    ])('rejects %s', (_case, change) => {
        const value: CustomShortcutRow[] = [{ id: 'row-0', action: 'node.agent', chord: 'Alt+KeyB' }];

        expect(applyShortcutChange(value, change)).toMatchObject({ accepted: false, rejection: 'params' });
    });

    it('reports a key problem before a missing flow', () => {
        expect(
            applyShortcutChange(NO_ROWS, { kind: 'add-custom', id: 'new', action: 'node.subgraph', chord: 'Mod+KeyC' })
        ).toMatchObject({ accepted: false, rejection: 'reserved' });
    });

    it('adds a second Subgraph row for the same flow on another key', () => {
        const result = applyShortcutChange([subgraphRow('row-0', 'Alt+Digit1', { flowId: 12 })], {
            kind: 'add-custom',
            id: 'new',
            action: 'node.subgraph',
            chord: 'Alt+Digit2',
            params: { flowId: 12 },
        });

        expect(rowsAfter(result)).toStrictEqual([
            { id: 'row-0', action: 'node.subgraph', chord: 'Alt+Digit1', params: { flowId: 12 } },
            { id: 'new', action: 'node.subgraph', chord: 'Alt+Digit2', params: { flowId: 12 } },
        ]);
    });

    it('moves an edited row to another flow and drops the flow when it becomes another action', () => {
        const value = [
            subgraphRow('row-0', 'Alt+Digit1', { flowId: 12 }),
            subgraphRow('row-1', 'Alt+Digit2', { flowId: 34 }),
        ];

        const moved = rowsAfter(
            applyShortcutChange(value, {
                kind: 'update-custom',
                id: 'row-0',
                action: 'node.subgraph',
                chord: 'Alt+Digit1',
                params: { flowId: 56 },
            })
        );
        const retyped = rowsAfter(
            applyShortcutChange(moved, {
                kind: 'update-custom',
                id: 'row-1',
                action: 'node.agent',
                chord: 'Alt+Digit2',
                params: { flowId: 34 },
            })
        );

        expect(retyped).toStrictEqual([
            { id: 'row-0', action: 'node.subgraph', chord: 'Alt+Digit1', params: { flowId: 56 } },
            { id: 'row-1', action: 'node.agent', chord: 'Alt+Digit2' },
        ]);
    });

    it('keeps a Subgraph row and its flow through a reset to defaults, clearing only a node key it took', () => {
        const value = [
            subgraphRow('row-0', 'Shift+KeyP', { flowId: 12 }),
            subgraphRow('row-1', 'Alt+Digit2', { flowId: 34 }),
        ];

        const reset = rowsAfter(applyShortcutChange(value, { kind: 'reset-to-defaults' }));

        expect(reset).toStrictEqual([
            { id: 'row-0', action: 'node.subgraph', chord: null, params: { flowId: 12 } },
            { id: 'row-1', action: 'node.subgraph', chord: 'Alt+Digit2', params: { flowId: 34 } },
        ]);
    });

    it('stores params only for rows that carry them', () => {
        const settings = toShortcutSettings([
            subgraphRow('row-0', 'Alt+Digit1', { flowId: 12 }),
            { id: 'row-1', action: 'node.agent', chord: 'Alt+KeyB' },
            { id: 'row-2', action: 'node.task', chord: null, params: {} },
        ]);

        expect(settings).toStrictEqual({
            custom: [
                { action: 'node.subgraph', keys: 'Alt+Digit1', params: { flowId: 12 } },
                { action: 'node.agent', keys: 'Alt+KeyB' },
                { action: 'node.task', keys: null },
            ],
        });
        expect(Number.isInteger(settings.custom[0].params?.['flowId'])).toBe(true);
    });

    it.each<[string, ShortcutParams | undefined, ShortcutParams | undefined, boolean]>([
        ['the same params with keys in another order', { flowId: 12, tab: 'a' }, { tab: 'a', flowId: 12 }, true],
        ['another flow', { flowId: 12 }, { flowId: 13 }, false],
        ['a flow on one side only', { flowId: 12 }, undefined, false],
        ['an extra key on one side', { flowId: 12 }, { flowId: 12, tab: 'a' }, false],
    ])('compares stored and current rows with %s', (_case, stored, current, same) => {
        const entries = [subgraphEntry(stored)];
        const value = [subgraphRow('row-0', 'Alt+Digit1', current)];

        expect(haveSameEntries(entries, value)).toBe(same);
        expect(identifyRows(entries, value, () => 'new').map((row) => row.id)).toEqual([same ? 'row-0' : 'new']);
    });

    it.each<[string, unknown, ShortcutParams | undefined]>([
        ['a flow', { flowId: 12 }, { flowId: 12 }],
        ['text and number values', { flowId: 12, tab: 'a' }, { flowId: 12, tab: 'a' }],
        ['a nested value', { flowId: { id: 12 } }, undefined],
        ['a list', [12], undefined],
        ['null', null, undefined],
    ])('reads a stored row whose params are %s', (_case, params, expected) => {
        const [entry] = readCustomEntries({ custom: [{ action: 'node.subgraph', keys: 'Alt+Digit1', params }] });

        expect(entry).toStrictEqual(subgraphEntry(expected));
    });
});
