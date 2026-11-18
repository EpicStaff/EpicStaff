import { inputMapFromRows, InputMapRow, isUnfinishedInputMapRow } from './input-map-rows';

describe('inputMapFromRows', () => {
    it.each<{ rows: InputMapRow[]; saved: Record<string, string>; case: string }>([
        { case: 'an untouched new row', rows: [{ key: '', value: 'variables.' }], saved: {} },
        { case: 'a row with no name and no path', rows: [{ key: '  ', value: '' }], saved: {} },
        { case: 'a row with null name and path', rows: [{ key: null, value: null }], saved: {} },
        {
            case: 'a filled row',
            rows: [{ key: 'topic', value: 'variables.topic|none' }],
            saved: { topic: 'variables.topic|none' },
        },
        { case: 'a named row with an empty path', rows: [{ key: 'topic', value: '' }], saved: { topic: '' } },
        { case: 'a named row with a null path', rows: [{ key: 'topic', value: null }], saved: { topic: '' } },
        {
            case: 'a named row on the new-row path',
            rows: [{ key: ' topic ', value: 'variables.' }],
            saved: { topic: 'variables.' },
        },
    ])('saves $case as $saved', ({ rows, saved }) => {
        expect(inputMapFromRows(rows)).toEqual(saved);
    });

    it('keeps the filled and named rows of a list, in order, and leaves out the empty one between them', () => {
        const saved = inputMapFromRows([
            { key: 'topic', value: 'variables.topic' },
            { key: '', value: 'variables.' },
            { key: 'user', value: '' },
        ]);

        expect(Object.entries(saved)).toEqual([
            ['topic', 'variables.topic'],
            ['user', ''],
        ]);
    });
});

describe('isUnfinishedInputMapRow', () => {
    it.each<{ row: InputMapRow; unfinished: boolean }>([
        { row: { key: 'topic', value: '' }, unfinished: true },
        { row: { key: 'topic', value: null }, unfinished: true },
        { row: { key: 'topic', value: '  ' }, unfinished: true },
        // A default does not make a path.
        { row: { key: 'topic', value: '|none' }, unfinished: true },
        // The new-row path maps all fields, the whole variables root.
        { row: { key: 'topic', value: 'variables.' }, unfinished: false },
        { row: { key: 'topic', value: 'variables' }, unfinished: false },
        { row: { key: 'topic', value: 'variables.|none' }, unfinished: false },
        { row: { key: 'topic', value: 'variables.topic' }, unfinished: false },
        { row: { key: 'topic', value: 'variables.topic|none' }, unfinished: false },
        { row: { key: 'topic', value: 'variables.variables' }, unfinished: false },
        // A row without a name is empty, not unfinished: saving leaves it out.
        { row: { key: '', value: 'variables.' }, unfinished: false },
        { row: { key: ' ', value: '' }, unfinished: false },
        { row: { key: null, value: null }, unfinished: false },
    ])('$row is unfinished: $unfinished', ({ row, unfinished }) => {
        expect(isUnfinishedInputMapRow(row)).toBe(unfinished);
    });
});
