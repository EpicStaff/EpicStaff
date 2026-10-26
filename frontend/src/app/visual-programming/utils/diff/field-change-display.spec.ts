import {
    DisplaySegment,
    fieldChangeFor,
    fieldValueSegments,
    mapFieldRowChanges,
    MapKeyChange,
    showsFieldMarks,
} from './field-change-display';
import { FieldChange } from './types';

/** The tooltip segments of a change that has no field (no formatter, no default), e.g. one key of a map. */
const segmentsOf = (current: unknown, version: unknown): DisplaySegment[] => fieldValueSegments(null, current, version);

/** The row changes of an `input_map` that a restore changes from `current` to `version`. */
function rowChangesOf(current: unknown, version: unknown): MapKeyChange[] {
    const change: FieldChange = { path: 'input_map', field: 'input_map', status: 'changed', current, version };
    return mapFieldRowChanges({ status: 'changed', fields: [change], missingReferences: [] }, 'input_map') ?? [];
}

const kept = (text: string): DisplaySegment => ({ text, struck: false });
const struck = (text: string): DisplaySegment => ({ text, struck: true });

describe('the tooltip segments of a value', () => {
    it.each<{ kind: string; current: unknown; version: unknown; segments: DisplaySegment[] }>([
        {
            kind: 'text changed in the middle',
            current: 'variables.previous_name',
            version: 'variables.name',
            segments: [kept('variables.'), struck('previous_'), kept('name')],
        },
        {
            kind: 'text changed at the end',
            current: 'Fetch v1',
            version: 'Fetch v2',
            segments: [kept('Fetch v'), struck('1')],
        },
        {
            kind: 'text changed at the start',
            current: 'old_path',
            version: 'new_path',
            segments: [struck('old'), kept('_path')],
        },
        { kind: 'text replaced whole', current: 'abc', version: 'xyz', segments: [struck('abc')] },
        { kind: 'text a restore only adds to', current: 'ab', version: 'aXb', segments: [kept('a'), kept('b')] },
        {
            kind: 'text a restore empties',
            current: 'variables.result',
            version: null,
            segments: [struck('variables.result')],
        },
        {
            kind: 'a list',
            current: ['numpy', 'pandas', 'requests'],
            version: ['pandas', 'scipy'],
            segments: [struck('numpy'), kept(', '), kept('pandas'), kept(', '), struck('requests')],
        },
        {
            kind: 'an emoji, never split in half',
            current: 'ok 👍',
            version: 'ok 👎',
            segments: [kept('ok '), struck('👍')],
        },
        {
            kind: 'an emoji with a skin tone, struck whole',
            current: 'hi 👍🏻',
            version: 'hi 👍🏿',
            segments: [kept('hi '), struck('👍🏻')],
        },
        {
            kind: 'a letter with a combining accent, struck with its accent',
            current: 'cafe\u0301',
            version: 'cafe\u0300',
            segments: [kept('caf'), struck('e\u0301')],
        },
        {
            kind: 'a list with a repeated item the version has once',
            current: ['numpy', 'numpy', 'pandas'],
            version: ['numpy', 'pandas'],
            segments: [kept('numpy'), kept(', '), struck('numpy'), kept(', '), kept('pandas')],
        },
        { kind: 'a number', current: 30, version: 60, segments: [struck('30')] },
        { kind: 'a flag on', current: true, version: false, segments: [struck('on')] },
        { kind: 'a flag off', current: false, version: true, segments: [struck('off')] },
        { kind: 'null', current: null, version: 'x', segments: [struck('empty')] },
        { kind: 'empty text', current: '', version: 'x', segments: [struck('empty')] },
        { kind: 'an empty list', current: [], version: ['x'], segments: [struck('empty')] },
        { kind: 'an empty map', current: {}, version: { a: 1 }, segments: [struck('empty')] },
        {
            kind: 'a structured value, as its JSON text',
            current: { a: 1, b: 2 },
            version: { a: 1, b: 3 },
            segments: [kept('{"a":1,"b":'), struck('2'), kept('}')],
        },
    ])('splits $kind', ({ current, version, segments }) => {
        expect(segmentsOf(current, version)).toEqual(segments);
    });
});

describe('the row changes of a map field', () => {
    it('lists the keys a restore changes and adds in version order, then the keys it removes', () => {
        const current = { kept: 'variables.kept', renamed: 'variables.old', gone: 'variables.gone' };
        const version = { fresh: 'variables.fresh', renamed: 'variables.new', kept: 'variables.kept' };

        expect(rowChangesOf(current, version)).toEqual<MapKeyChange[]>([
            { key: 'fresh', status: 'added', current: null, version: 'variables.fresh' },
            { key: 'renamed', status: 'changed', current: 'variables.old', version: 'variables.new' },
            { key: 'gone', status: 'deleted', current: 'variables.gone', version: null },
        ]);
    });

    it.each([
        { kind: 'null on the canvas', current: null, version: { a: 'x' }, keys: [['a', 'added']] },
        { kind: 'null in the version', current: { a: 'x' }, version: null, keys: [['a', 'deleted']] },
        { kind: 'a list instead of a map', current: ['a'], version: {}, keys: [] },
        { kind: 'two equal maps', current: { a: 'x' }, version: { a: 'x' }, keys: [] },
    ])('reads $kind as an empty map or no change', ({ current, version, keys }) => {
        expect(rowChangesOf(current, version).map((change) => [change.key, change.status])).toEqual(keys);
    });

    it('treats a key like __proto__ as a plain key', () => {
        const version = JSON.parse('{"__proto__": "variables.x"}') as Record<string, unknown>;

        expect(rowChangesOf({}, version)).toEqual([
            { key: '__proto__', status: 'added', current: null, version: 'variables.x' },
        ]);
    });
});

describe('fieldChangeFor', () => {
    const renamed: FieldChange = {
        path: 'node_name',
        field: 'node_name',
        status: 'changed',
        current: 'A',
        version: 'B',
    };
    const groupExpression: FieldChange = {
        path: 'condition_groups[name=yes].expression',
        field: 'condition_groups[].expression',
        status: 'changed',
        current: 'a > 1',
        version: 'a > 2',
    };
    const diff = { fields: [renamed, groupExpression] };

    it('finds the change of a field, or of one item of it by its path', () => {
        expect(fieldChangeFor(diff, 'node_name')).toBe(renamed);
        expect(fieldChangeFor(diff, 'condition_groups[].expression', 'condition_groups[name=yes].expression')).toBe(
            groupExpression
        );
    });

    it('finds nothing for an unchanged field, another item, or no diff', () => {
        expect(fieldChangeFor(diff, 'output_variable_path')).toBeNull();
        expect(
            fieldChangeFor(diff, 'condition_groups[].expression', 'condition_groups[name=no].expression')
        ).toBeNull();
        expect(fieldChangeFor(diff, 'condition_groups[].expression')).toBeNull();
        expect(fieldChangeFor(null, 'node_name')).toBeNull();
    });
});

describe('showsFieldMarks and mapFieldRowChanges', () => {
    const inputMapChange: FieldChange = {
        path: 'input_map',
        field: 'input_map',
        status: 'changed',
        current: { user: 'variables.user' },
        version: { user: 'variables.account' },
    };

    it.each([
        { status: 'changed' as const, shows: true },
        { status: 'unchanged' as const, shows: false },
        { status: 'added' as const, shows: false },
        { status: 'deleted' as const, shows: false },
    ])('marks fields only on a node a restore changes ($status)', ({ status, shows }) => {
        const diff = { status, fields: [inputMapChange], missingReferences: [] };

        expect(showsFieldMarks(diff)).toBe(shows);
        expect(mapFieldRowChanges(diff, 'input_map') !== null).toBe(shows);
    });

    it('gives the row changes of a changed map field, and none for an unchanged field or no diff', () => {
        const diff = { status: 'changed' as const, fields: [inputMapChange], missingReferences: [] };

        expect(mapFieldRowChanges(diff, 'input_map')).toEqual([
            { key: 'user', status: 'changed', current: 'variables.user', version: 'variables.account' },
        ]);
        expect(mapFieldRowChanges(diff, 'output_map')).toBeNull();
        expect(mapFieldRowChanges(null, 'input_map')).toBeNull();
    });
});

describe('fieldValueSegments', () => {
    it.each([
        'python_code.execution_timeout',
        'pre_computation.execution_timeout',
        'post_computation.execution_timeout',
    ] as const)('shows %s as the clock the field shows, struck as a whole', (field) => {
        // By character, 00:01:30 against 00:02:00 would strike only "1:3".
        expect(fieldValueSegments(field, 90, 120)).toEqual([struck('00:01:30')]);
    });

    it.each<{ kind: string; current: unknown; version: unknown; segments: DisplaySegment[] }>([
        { kind: 'no own timeout on the canvas', current: null, version: 90, segments: [struck('00:02:00')] },
        { kind: 'no own timeout in the version', current: 90, version: null, segments: [struck('00:01:30')] },
        // The field reads the same either way: nothing is struck.
        {
            kind: 'no own timeout, the version setting the default',
            current: null,
            version: 120,
            segments: [kept('00:02:00')],
        },
        {
            kind: 'the default set on the canvas, none in the version',
            current: 120,
            version: null,
            segments: [kept('00:02:00')],
        },
    ])('shows the default the field shows for $kind', ({ current, version, segments }) => {
        expect(fieldValueSegments('python_code.execution_timeout', current, version, 120)).toEqual(segments);
    });

    it('says "empty" for a side without a value when the field has no default', () => {
        expect(fieldValueSegments('python_code.execution_timeout', null, 90)).toEqual([struck('empty')]);
    });

    it('splits a field without a formatter, or a change with no field, by character', () => {
        const parts = [kept('variables.'), struck('previous_'), kept('name')];

        expect(fieldValueSegments('output_variable_path', 'variables.previous_name', 'variables.name')).toEqual(parts);
        expect(fieldValueSegments(null, 'variables.previous_name', 'variables.name')).toEqual(parts);
    });
});

describe('the tooltip segments of a long value', () => {
    const a40 = 'a'.repeat(40);
    const b40 = 'b'.repeat(40);

    it.each<{ kind: string; current: unknown; version: unknown; segments: DisplaySegment[] }>([
        {
            kind: 'a change near the end: the start is cut',
            current: `${'a'.repeat(60)}X`,
            version: `${'a'.repeat(60)}Y`,
            segments: [kept(`…${a40}`), struck('X')],
        },
        {
            kind: 'a change near the start: the end is cut',
            current: `X${'b'.repeat(60)}`,
            version: `Y${'b'.repeat(60)}`,
            segments: [struck('X'), kept(`${b40}…`)],
        },
        {
            kind: 'a change in the middle: both ends are cut',
            current: `${'a'.repeat(60)}X${'b'.repeat(60)}`,
            version: `${'a'.repeat(60)}Y${'b'.repeat(60)}`,
            segments: [kept(`…${a40}`), struck('X'), kept(`${b40}…`)],
        },
        {
            kind: 'exactly 40 characters on each side: nothing is cut',
            current: `${a40}X${b40}`,
            version: `${a40}Y${b40}`,
            segments: [kept(a40), struck('X'), kept(b40)],
        },
        {
            kind: 'emoji context: cut between whole emoji',
            current: `${'👍🏻'.repeat(45)}X`,
            version: `${'👍🏻'.repeat(45)}Y`,
            segments: [kept(`…${'👍🏻'.repeat(40)}`), struck('X')],
        },
        {
            kind: 'a structured value, cut as its JSON text',
            current: { note: `${'a'.repeat(60)}X` },
            version: { note: `${'a'.repeat(60)}Y` },
            segments: [kept(`…${'a'.repeat(40)}`), struck('X'), kept('"}')],
        },
    ])('keeps 40 characters around the change for $kind', ({ current, version, segments }) => {
        expect(segmentsOf(current, version)).toEqual(segments);
    });
});

describe('the tooltip segments of a long replaced part', () => {
    it.each<{ kind: string; current: unknown; version: unknown; segments: DisplaySegment[] }>([
        {
            kind: 'a rewritten long text: its two ends, an unstruck "…" between them',
            current: `${'x'.repeat(50)}${'m'.repeat(100)}${'z'.repeat(50)}`,
            version: 'other',
            segments: [struck('x'.repeat(50)), kept('…'), struck('z'.repeat(50))],
        },
        {
            kind: 'exactly 120 characters replaced: not cut',
            current: 'x'.repeat(120),
            version: 'other',
            segments: [struck('x'.repeat(120))],
        },
        {
            kind: 'a long emoji run: cut between whole emoji',
            current: '👍🏻'.repeat(130),
            version: 'other',
            segments: [struck('👍🏻'.repeat(50)), kept('…'), struck('👍🏻'.repeat(50))],
        },
        {
            kind: 'a long replaced middle with long context: everything capped',
            current: `${'a'.repeat(60)}${'x'.repeat(200)}${'b'.repeat(60)}`,
            version: `${'a'.repeat(60)}Y${'b'.repeat(60)}`,
            segments: [
                kept(`…${'a'.repeat(40)}`),
                struck('x'.repeat(50)),
                kept('…'),
                struck('x'.repeat(50)),
                kept(`${'b'.repeat(40)}…`),
            ],
        },
        {
            kind: 'a list with a long struck item and a long kept item: each capped',
            current: [{ note: 'x'.repeat(200) }, 'k'.repeat(60)],
            version: ['k'.repeat(60)],
            segments: [
                struck(`{"note":"${'x'.repeat(41)}`),
                kept('…'),
                struck(`${'x'.repeat(48)}"}`),
                kept(', '),
                kept(`${'k'.repeat(40)}…`),
            ],
        },
        {
            kind: 'a long list item of emoji: cut between whole emoji',
            current: ['👍🏻'.repeat(130)],
            version: [],
            segments: [struck('👍🏻'.repeat(50)), kept('…'), struck('👍🏻'.repeat(50))],
        },
    ])('keeps $kind', ({ current, version, segments }) => {
        expect(segmentsOf(current, version)).toEqual(segments);
    });
});
