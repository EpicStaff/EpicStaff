import { CAPTION_TABLE_NAME_LIMIT, KEY_VALUE_MODE_LABELS, keyValueSummaryParts } from './key-value-mode-visuals';

describe('key-value mode visuals', () => {
    it('gives every mode a word', () => {
        expect(KEY_VALUE_MODE_LABELS).toEqual({ read: 'Read', write: 'Write', delete: 'Delete' });
    });

    it('splits the summary into mode, table and key count', () => {
        expect(keyValueSummaryParts('write', 'customers', 3)).toEqual(['Write', 'customers', '3 keys']);
        expect(keyValueSummaryParts('read', 'customers', 1)).toEqual(['Read', 'customers', '1 key']);
        expect(keyValueSummaryParts('delete', null, 0)).toEqual(['Delete', 'no table', '0 keys']);
    });

    it('cuts a table name longer than the given limit to end in an ellipsis', () => {
        expect(keyValueSummaryParts('write', 'Very very long table name', 2, CAPTION_TABLE_NAME_LIMIT)).toEqual([
            'Write',
            'Very very long tabl…',
            '2 keys',
        ]);
        expect(keyValueSummaryParts('read', 'x'.repeat(CAPTION_TABLE_NAME_LIMIT), 1, CAPTION_TABLE_NAME_LIMIT)).toEqual(
            ['Read', 'x'.repeat(CAPTION_TABLE_NAME_LIMIT), '1 key']
        );
        expect(keyValueSummaryParts('delete', null, 0, CAPTION_TABLE_NAME_LIMIT)).toEqual([
            'Delete',
            'no table',
            '0 keys',
        ]);
    });
});
