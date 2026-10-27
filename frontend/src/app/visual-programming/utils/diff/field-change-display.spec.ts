import {
    changesAnyFieldIn,
    codeChangeFor,
    DisplaySegment,
    fieldChangeFor,
    fieldGroupChange,
    fieldValueSegments,
    jsonChangeFor,
    keyedItemChanges,
    keyedListRowChanges,
    linkedEntityFormat,
    mapFieldRowChanges,
    MapKeyChange,
    reordersKeyedList,
    showsFieldMarks,
} from './field-change-display';
import { FieldName } from './field-display';
import { FieldChange, NodeDiffStatus } from './types';

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

describe('codeChangeFor', () => {
    const codeChange = (field: FieldName, current: unknown, version: unknown): FieldChange => ({
        path: field,
        field,
        status: 'changed',
        current,
        version,
    });
    const diffOf = (status: NodeDiffStatus, fields: FieldChange[]) => ({ status, fields, missingReferences: [] });

    it.each([
        { case: 'both sides', current: 'a = 1', version: 'a = 2', expected: { current: 'a = 1', version: 'a = 2' } },
        { case: 'no code on the canvas', current: null, version: 'a = 2', expected: { current: '', version: 'a = 2' } },
        {
            case: 'no code in the version',
            current: 'a = 1',
            version: null,
            expected: { current: 'a = 1', version: '' },
        },
    ])('gives both sides of a changed code as text: $case', ({ current, version, expected }) => {
        const diff = diffOf('changed', [codeChange('pre_computation.code', current, version)]);

        expect(codeChangeFor(diff, 'pre_computation.code')).toEqual(expected);
    });

    it('gives nothing for unchanged code, another code field, or no diff', () => {
        const diff = diffOf('changed', [codeChange('pre_computation.code', 'a = 1', 'a = 2')]);

        expect(codeChangeFor(diff, 'post_computation.code')).toBeNull();
        expect(codeChangeFor(diffOf('changed', []), 'python_code.code')).toBeNull();
        expect(codeChangeFor(null, 'python_code.code')).toBeNull();
    });

    it.each(['added', 'deleted', 'unchanged'] as const)('gives nothing on a node whose status is %s', (status) => {
        const diff = diffOf(status, [codeChange('python_code.code', 'a = 1', 'a = 2')]);

        expect(codeChangeFor(diff, 'python_code.code')).toBeNull();
    });
});

describe('changesAnyFieldIn', () => {
    const PRE_COMPUTATION_TAB: FieldName[] = ['pre_computation', 'pre_use_storage'];
    const changeOf = (field: FieldName, path: string = field): FieldChange => ({
        path,
        field,
        status: 'changed',
        current: 1,
        version: 2,
    });

    it.each([
        { changed: changeOf('pre_computation.code'), expected: true },
        { changed: changeOf('pre_computation.execution_timeout'), expected: true },
        { changed: changeOf('pre_use_storage'), expected: true },
        { changed: changeOf('pre_computation'), expected: true },
        { changed: changeOf('post_computation.code'), expected: false },
        { changed: changeOf('post_use_storage'), expected: false },
        { changed: changeOf('node_name'), expected: false },
    ])('is $expected when a restore changes $changed.field', ({ changed, expected }) => {
        const diff = { status: 'changed' as const, fields: [changed], missingReferences: [] };

        expect(changesAnyFieldIn(diff, PRE_COMPUTATION_TAB)).toBe(expected);
    });

    it.each(['added', 'deleted'] as const)('is false on a node whose status is %s, and with no diff', (status) => {
        const diff = { status, fields: [changeOf('pre_computation.code')], missingReferences: [] };

        expect(changesAnyFieldIn(diff, PRE_COMPUTATION_TAB)).toBe(false);
        expect(changesAnyFieldIn(null, PRE_COMPUTATION_TAB)).toBe(false);
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

describe('fieldValueSegments with a display format of its own', () => {
    const flowNames = new Map<unknown, string>([
        [41, 'Billing'],
        [42, 'Refunds'],
    ]);
    const flowName = linkedEntityFormat('flow', (id) => flowNames.get(id));

    it.each<{ kind: string; current: unknown; version: unknown; segments: DisplaySegment[] }>([
        { kind: 'both sides named', current: 41, version: 42, segments: [struck('Billing')] },
        { kind: 'the canvas side not among the names', current: 7, version: 42, segments: [struck('flow #7')] },
        { kind: 'no value on the canvas', current: null, version: 42, segments: [struck('empty')] },
        { kind: 'the same name on both sides', current: 41, version: 41, segments: [kept('Billing')] },
    ])('shows a linked entity by name: $kind', ({ current, version, segments }) => {
        expect(fieldValueSegments(null, current, version, undefined, flowName)).toEqual(segments);
    });

    it("replaces the field's own formatter", () => {
        const asSeconds = (value: unknown): string => `${String(value)} s`;

        expect(fieldValueSegments('python_code.execution_timeout', 90, 120, undefined, asSeconds)).toEqual([
            struck('90 s'),
        ]);
    });
});

describe('jsonChangeFor', () => {
    const diffOf = (status: NodeDiffStatus, fields: FieldChange[]) => ({ status, fields, missingReferences: [] });
    const outputMapChange: FieldChange = {
        path: 'output_map',
        field: 'output_map',
        status: 'changed',
        current: { answer: 'variables.a' },
        version: { answer: 'variables.b', extra: 1 },
    };

    it('gives both sides as the JSON editor shows them, indented by 2', () => {
        expect(jsonChangeFor(diffOf('changed', [outputMapChange]), 'output_map')).toEqual({
            current: '{\n  "answer": "variables.a"\n}',
            version: '{\n  "answer": "variables.b",\n  "extra": 1\n}',
        });
    });

    it.each(['added', 'deleted', 'unchanged'] as const)('gives nothing on a node whose status is %s', (status) => {
        expect(jsonChangeFor(diffOf(status, [outputMapChange]), 'output_map')).toBeNull();
    });

    it('gives nothing for an unchanged field or with no diff', () => {
        expect(jsonChangeFor(diffOf('changed', [outputMapChange]), 'variables')).toBeNull();
        expect(jsonChangeFor(null, 'output_map')).toBeNull();
    });
});

describe('keyedListRowChanges', () => {
    const entriesChange = (current: unknown, version: unknown) => ({
        status: 'changed' as const,
        fields: [{ path: 'entries', field: 'entries', status: 'changed' as const, current, version }],
        missingReferences: [],
    });
    const keyOf = (entry: unknown): string => (entry as { key: string }).key;
    const entry = (key: string, value?: string) => (value === undefined ? { key } : { key, value });

    it('pairs the rows by key, in the version order, and lists the rows only the canvas has', () => {
        const changes = keyedListRowChanges(
            entriesChange(
                [entry('kept', 'variables.kept'), entry('moved', 'variables.old'), entry('gone', 'variables.gone')],
                [entry('moved', 'variables.new'), entry('new', 'variables.new'), entry('kept', 'variables.kept')]
            ),
            'entries',
            keyOf
        );

        expect(changes).toEqual({
            rows: [
                {
                    key: 'moved',
                    status: 'changed',
                    current: entry('moved', 'variables.old'),
                    version: entry('moved', 'variables.new'),
                },
                { key: 'new', status: 'added', current: null, version: entry('new', 'variables.new') },
                null,
            ],
            removed: [{ key: 'gone', status: 'deleted', current: entry('gone', 'variables.gone'), version: null }],
        });
    });

    it('pairs a repeated key by its occurrence', () => {
        const changes = keyedListRowChanges(
            entriesChange(
                [entry('user', 'variables.a'), entry('user', 'variables.b')],
                [entry('user', 'variables.a'), entry('user', 'variables.c'), entry('user', 'variables.d')]
            ),
            'entries',
            keyOf
        );

        expect(changes?.rows.map((row) => row?.status ?? null)).toEqual([null, 'changed', 'added']);
        expect(changes?.removed).toEqual([]);
    });

    it('treats a side that is not a list as no rows', () => {
        const changes = keyedListRowChanges(entriesChange(null, [entry('user')]), 'entries', keyOf);

        expect(changes).toEqual({
            rows: [{ key: 'user', status: 'added', current: null, version: entry('user') }],
            removed: [],
        });
    });

    it('gives nothing for an unchanged field, a node not changed, or no diff', () => {
        const diff = entriesChange([entry('a')], [entry('b')]);

        expect(keyedListRowChanges(diff, 'input_map', keyOf)).toBeNull();
        expect(keyedListRowChanges({ ...diff, status: 'added' }, 'entries', keyOf)).toBeNull();
        expect(keyedListRowChanges(null, 'entries', keyOf)).toBeNull();
    });
});

describe('reordersKeyedList', () => {
    const entriesChange = (current: unknown, version: unknown) => ({
        status: 'changed' as const,
        fields: [{ path: 'entries', field: 'entries', status: 'changed' as const, current, version }],
        missingReferences: [],
    });
    const keyOf = (entry: unknown): string => (entry as { key: string }).key;
    /** Entries from `key=path` texts; a text with no `=` has no path. */
    const entries = (...texts: string[]) =>
        texts.map((text) => {
            const [key, value] = text.split('=');
            return value === undefined ? { key } : { key, value };
        });

    it.each<{ case: string; current: string[]; version: string[]; reorders: boolean }>([
        { case: 'the same order', current: ['a', 'b', 'c'], version: ['a', 'b', 'c'], reorders: false },
        { case: 'a reorder alone', current: ['a', 'b', 'c'], version: ['c', 'a', 'b'], reorders: true },
        {
            case: 'a reorder with changed rows',
            current: ['a=variables.x', 'b=variables.y'],
            version: ['b=variables.z', 'a=variables.x'],
            reorders: true,
        },
        {
            case: 'changed rows in the same order',
            current: ['a=variables.x', 'b=variables.y'],
            version: ['a=variables.z', 'b=variables.y'],
            reorders: false,
        },
        {
            case: 'added and removed keys only',
            current: ['a', 'gone', 'b'],
            version: ['new', 'a', 'b'],
            reorders: false,
        },
        {
            // Paired by occurrence: the first `user` with the first, so swapping two `user` rows changes rows instead.
            case: 'repeated keys swapped among themselves',
            current: ['user=variables.a', 'user=variables.b'],
            version: ['user=variables.b', 'user=variables.a'],
            reorders: false,
        },
        {
            case: 'a repeated key moved past another key',
            current: ['a', 'b', 'a'],
            version: ['a', 'a', 'b'],
            reorders: true,
        },
        { case: 'a side that is not a list', current: [], version: ['a', 'b'], reorders: false },
    ])('$case: $reorders', ({ current, version, reorders }) => {
        expect(reordersKeyedList(entriesChange(entries(...current), entries(...version)), 'entries', keyOf)).toBe(
            reorders
        );
    });

    it('is false for an unchanged field, a node not changed, or no diff', () => {
        const diff = entriesChange(entries('a', 'b'), entries('b', 'a'));

        expect(reordersKeyedList(diff, 'input_map', keyOf)).toBe(false);
        expect(reordersKeyedList({ ...diff, status: 'added' }, 'entries', keyOf)).toBe(false);
        expect(reordersKeyedList(null, 'entries', keyOf)).toBe(false);
    });
});

describe('keyedItemChanges', () => {
    const diffOf = (fields: FieldChange[], status: NodeDiffStatus = 'changed') => ({
        status,
        fields,
        missingReferences: [],
    });
    const itemChange = (path: string, field: string, current: unknown, version: unknown): FieldChange => ({
        path,
        field,
        status: 'changed',
        current,
        version,
    });
    const TASK = { name: 'Review', instructions: 'Check it', output_schema: {}, context_tasks: [1] };

    it('gathers the changed fields of each item, then gives the items a restore adds or removes whole', () => {
        const changes = keyedItemChanges(
            diffOf([
                itemChange('tasks[1].name', 'tasks[].name', 'Old', 'Research'),
                itemChange('tasks[1].context_tasks', 'tasks[].context_tasks', [2], []),
                { path: 'tasks[2]', field: 'tasks[]', status: 'added', current: null, version: TASK },
                { path: 'tasks[3]', field: 'tasks[]', status: 'deleted', current: TASK, version: null },
                itemChange('node_name', 'node_name', 'a', 'b'),
            ]),
            'tasks'
        );

        expect(changes).toEqual([
            {
                key: '1',
                status: 'changed',
                fields: ['name', 'context_tasks'],
                current: { name: 'Old', context_tasks: [2] },
                version: { name: 'Research', context_tasks: [] },
            },
            { key: '2', status: 'added', fields: [], current: null, version: TASK },
            { key: '3', status: 'deleted', fields: [], current: TASK, version: null },
        ]);
    });

    it('reads a key written with its prefix, even one holding brackets and dots', () => {
        const changes = keyedItemChanges(
            diffOf([
                itemChange('condition_groups[name=a].b].expression', 'condition_groups[].expression', 'x > 1', 'x > 2'),
            ]),
            'condition_groups'
        );

        expect(changes?.map(({ key, fields }) => ({ key, fields }))).toEqual([{ key: 'a].b', fields: ['expression'] }]);
    });

    it('gives nothing when no item changed, on a node not changed, or with no diff', () => {
        const nameChange = itemChange('tasks[1].name', 'tasks[].name', 'Old', 'Research');

        expect(keyedItemChanges(diffOf([itemChange('node_name', 'node_name', 'a', 'b')]), 'tasks')).toBeNull();
        expect(keyedItemChanges(diffOf([nameChange]), 'condition_groups')).toBeNull();
        expect(keyedItemChanges(diffOf([nameChange], 'added'), 'tasks')).toBeNull();
        expect(keyedItemChanges(null, 'tasks')).toBeNull();
    });
});

describe('the tooltip of a schedule date and time', () => {
    it.each([
        { field: 'start_date_time' as const, current: '2026-06-30T08:15:00', text: '30.06.2026 at 08:15' },
        { field: 'end_date_time' as const, current: '2026-12-01T23:05:00+02:00', text: '01.12.2026 at 23:05' },
    ])('shows $current as the date and time pickers do: $text', ({ field, current, text }) => {
        expect(fieldValueSegments(field, current, '2026-07-01T12:00:00')).toEqual([struck(text)]);
    });

    it('strikes nothing when both sides show the same minute', () => {
        expect(fieldValueSegments('start_date_time', '2026-07-01T12:00:00', '2026-07-01T12:00:30')).toEqual([
            kept('01.07.2026 at 12:00'),
        ]);
    });

    it('shows a value it cannot read as it is, and no value as empty', () => {
        expect(fieldValueSegments('end_date_time', 'soon', null)).toEqual([struck('soon')]);
        expect(fieldValueSegments('end_date_time', null, '2026-07-01T12:00:00')).toEqual([struck('empty')]);
    });
});

describe('fieldGroupChange', () => {
    const change = (field: FieldName, current: unknown, version: unknown): FieldChange => ({
        path: field,
        field,
        status: 'changed',
        current,
        version,
    });
    const diffOf = (fields: FieldChange[], status: NodeDiffStatus = 'changed') => ({
        status,
        fields,
        missingReferences: [],
    });
    const SHOWN = { rag_type: 'naive', rag_id: 8 };

    it('gives each side as all the fields, the unchanged ones as the panel shows them', () => {
        expect(fieldGroupChange(diffOf([change('rag_id', 3, 8)]), SHOWN)).toEqual({
            current: { rag_type: 'naive', rag_id: 3 },
            version: { rag_type: 'naive', rag_id: 8 },
        });
    });

    it('keeps a side a restore sets to null, and gives a side with nothing picked as null', () => {
        expect(fieldGroupChange(diffOf([change('rag_type', null, 'naive'), change('rag_id', null, 8)]), SHOWN)).toEqual(
            { current: null, version: { rag_type: 'naive', rag_id: 8 } }
        );
        expect(fieldGroupChange(diffOf([change('rag_type', 'graph', null)]), { ...SHOWN, rag_type: null })).toEqual({
            current: { rag_type: 'graph', rag_id: 8 },
            version: { rag_type: null, rag_id: 8 },
        });
    });

    it('gives nothing when none of the fields changed, on a node not changed, or with no diff', () => {
        expect(fieldGroupChange(diffOf([change('node_name', 'a', 'b')]), SHOWN)).toBeNull();
        expect(fieldGroupChange(diffOf([change('rag_id', 3, 8)], 'deleted'), SHOWN)).toBeNull();
        expect(fieldGroupChange(null, SHOWN)).toBeNull();
    });
});

describe('the tooltip segments of a long value', () => {
    // One letter per region, so a cut in the wrong place shows: the start of the value (40), a part dropped
    // between it and the change, the context right before the change (20), and the text after it.
    const start = 's'.repeat(40);
    const dropped = 'm'.repeat(30);
    const before = 'c'.repeat(20);
    const after = 'd'.repeat(20);

    it.each<{ kind: string; current: unknown; version: unknown; segments: DisplaySegment[] }>([
        {
            kind: 'a change near the end: the start, "…", the context before the change',
            current: `${start}${dropped}${before}X`,
            version: `${start}${dropped}${before}Y`,
            segments: [kept(`${start}…${before}`), struck('X')],
        },
        {
            kind: 'a change in the middle: the start, "…", the context on both sides, "…"',
            current: `${start}${dropped}${before}X${after}${'e'.repeat(30)}`,
            version: `${start}${dropped}${before}Y${after}${'e'.repeat(30)}`,
            segments: [kept(`${start}…${before}`), struck('X'), kept(`${after}…`)],
        },
        {
            kind: 'a change at the start: the context after it, "…"',
            current: `X${after}${'e'.repeat(40)}`,
            version: `Y${after}${'e'.repeat(40)}`,
            segments: [struck('X'), kept(`${after}…`)],
        },
        {
            kind: 'a change inside the start: the start up to the change, no "…" before it',
            current: `${'s'.repeat(10)}X${after}${'e'.repeat(40)}`,
            version: `${'s'.repeat(10)}Y${after}${'e'.repeat(40)}`,
            segments: [kept('s'.repeat(10)), struck('X'), kept(`${after}…`)],
        },
        {
            kind: 'the start and the context before the change just meet: nothing dropped',
            current: `${start}${before}X${after}`,
            version: `${start}${before}Y${after}`,
            segments: [kept(`${start}${before}`), struck('X'), kept(after)],
        },
        {
            kind: 'one character between the start and the context before the change: dropped',
            current: `${start}m${before}X${after}e`,
            version: `${start}m${before}Y${after}e`,
            segments: [kept(`${start}…${before}`), struck('X'), kept(`${after}…`)],
        },
        {
            kind: 'a short text: nothing cut',
            current: 'the user name',
            version: 'the account name',
            segments: [kept('the '), struck('user'), kept(' name')],
        },
        {
            kind: 'emoji: cut between whole emoji',
            current: `${'👍🏻'.repeat(70)}X${'🎉'.repeat(25)}`,
            version: `${'👍🏻'.repeat(70)}Y${'🎉'.repeat(25)}`,
            segments: [kept(`${'👍🏻'.repeat(40)}…${'👍🏻'.repeat(20)}`), struck('X'), kept(`${'🎉'.repeat(20)}…`)],
        },
        {
            kind: 'a structured value, cut as its JSON text',
            current: { note: `${'a'.repeat(70)}X` },
            version: { note: `${'a'.repeat(70)}Y` },
            segments: [kept(`{"note":"${'a'.repeat(31)}…${'a'.repeat(20)}`), struck('X'), kept('"}')],
        },
    ])('shows $kind', ({ current, version, segments }) => {
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
            current: `${'s'.repeat(40)}${'m'.repeat(30)}${'c'.repeat(20)}${'x'.repeat(100)}${'z'.repeat(100)}${'d'.repeat(60)}`,
            version: `${'s'.repeat(40)}${'m'.repeat(30)}${'c'.repeat(20)}Y${'d'.repeat(60)}`,
            segments: [
                kept(`${'s'.repeat(40)}…${'c'.repeat(20)}`),
                struck('x'.repeat(50)),
                kept('…'),
                struck('z'.repeat(50)),
                kept(`${'d'.repeat(20)}…`),
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

describe('the tooltip segments of a value with many lines', () => {
    /** Short lines `l<from>` to `l<to>`, joined by `\n`. */
    const lines = (from: number, to: number, prefix = 'l'): string =>
        Array.from({ length: to - from + 1 }, (_, index) => `${prefix}${from + index}`).join('\n');

    it.each<{ kind: string; current: unknown; version: unknown; segments: DisplaySegment[] }>([
        {
            kind: 'many short lines before the change: the first 3 lines, "…", the 2 lines up to the change',
            current: `${lines(1, 7)} X tail`,
            version: `${lines(1, 7)} Y tail`,
            segments: [kept('l1\nl2\nl3…l6\nl7 '), struck('X'), kept(' tail')],
        },
        {
            kind: 'a change on a line of its own after 5 lines: the start and the context meet, nothing cut',
            current: `${lines(1, 4)}\nX`,
            version: `${lines(1, 4)}\nY`,
            segments: [kept('l1\nl2\nl3\nl4\n'), struck('X')],
        },
        {
            kind: 'a change on a line of its own after 6 lines: the line between the start and the context dropped',
            current: `${lines(1, 5)}\nX`,
            version: `${lines(1, 5)}\nY`,
            segments: [kept('l1\nl2\nl3…l5\n'), struck('X')],
        },
        {
            kind: 'many lines after the change: the rest of its line and 1 more line, "…"',
            current: `l1\nl2 X\n${lines(3, 6)}`,
            version: `l1\nl2 Y\n${lines(3, 6)}`,
            segments: [kept('l1\nl2 '), struck('X'), kept('\nl3…')],
        },
        {
            kind: 'only an empty last line after the 2 lines of context: nothing cut',
            current: 'X\nl2\n',
            version: 'Y\nl2\n',
            segments: [struck('X'), kept('\nl2\n')],
        },
        {
            kind: 'a change on the first line: no start before it, the context after it cut by lines',
            current: `X\n${lines(2, 9)}`,
            version: `Y\n${lines(2, 9)}`,
            segments: [struck('X'), kept('\nl2…')],
        },
        {
            kind: 'Windows line breaks: each \\r\\n one break, never split',
            current: `${lines(1, 6).replaceAll('\n', '\r\n')}\r\nX\r\n${lines(7, 9).replaceAll('\n', '\r\n')}`,
            version: `${lines(1, 6).replaceAll('\n', '\r\n')}\r\nY\r\n${lines(7, 9).replaceAll('\n', '\r\n')}`,
            segments: [kept('l1\r\nl2\r\nl3…l6\r\n'), struck('X'), kept('\r\nl7…')],
        },
        {
            kind: 'a long first line, then short lines: the start cut by graphemes, the context by lines',
            current: `${'s'.repeat(50)}\n${lines(2, 6)} X`,
            version: `${'s'.repeat(50)}\n${lines(2, 6)} Y`,
            segments: [kept(`${'s'.repeat(40)}…l5\nl6 `), struck('X')],
        },
        {
            kind: 'a value under both limits: untouched',
            current: 'first line\nsecond X line\nthird line',
            version: 'first line\nsecond Y line\nthird line',
            segments: [kept('first line\nsecond '), struck('X'), kept(' line\nthird line')],
        },
        {
            kind: 'a kept list item of many lines: its first 3 lines, "…"',
            current: [lines(1, 5), 'gone'],
            version: [lines(1, 5)],
            segments: [kept('l1\nl2\nl3…'), kept(', '), struck('gone')],
        },
    ])('shows $kind', ({ current, version, segments }) => {
        expect(segmentsOf(current, version)).toEqual(segments);
    });

    it.each<{ kind: string; current: unknown; version: unknown; segments: DisplaySegment[] }>([
        {
            kind: 'a replaced part of 7 lines: its first 3 lines, an unstruck "…", its last 3 lines',
            current: `keep\n${lines(1, 7, 'r')}`,
            version: 'keep\nother',
            segments: [kept('keep\n'), struck('r1\nr2\nr3'), kept('…'), struck('r5\nr6\nr7')],
        },
        {
            kind: 'a replaced part of exactly 6 lines: not cut',
            current: `keep\n${lines(1, 6, 'r')}`,
            version: 'keep\nother',
            segments: [kept('keep\n'), struck(lines(1, 6, 'r'))],
        },
        {
            kind: 'a replaced part of long lines: each end cut by graphemes first',
            current: [1, 2, 3, 4, 5, 6, 7].map((line) => `${line}`.repeat(30)).join('\n'),
            version: 'other',
            segments: [
                struck(`${'1'.repeat(30)}\n${'2'.repeat(19)}`),
                kept('…'),
                struck(`${'6'.repeat(19)}\n${'7'.repeat(30)}`),
            ],
        },
        {
            kind: 'a removed list item of many lines: capped like a replaced part',
            current: [lines(1, 8, 'r')],
            version: [],
            segments: [struck('r1\nr2\nr3'), kept('…'), struck('r6\nr7\nr8')],
        },
    ])('keeps $kind', ({ current, version, segments }) => {
        expect(segmentsOf(current, version)).toEqual(segments);
    });
});
