import {
    CAPTION_TABLE_NAME_LIMIT,
    KEY_VALUE_MODE_LABELS,
    keyValueCaption,
    keyValueSubtitle,
} from './key-value-mode-visuals';

describe('key-value mode visuals', () => {
    it('gives every mode a word', () => {
        expect(KEY_VALUE_MODE_LABELS).toEqual({ read: 'Read', write: 'Write', delete: 'Delete' });
    });

    it('formats the subtitle', () => {
        expect(keyValueSubtitle('write', 'customers', 3)).toBe('Write · customers · 3 keys');
        expect(keyValueSubtitle('read', 'customers', 1)).toBe('Read · customers · 1 key');
        expect(keyValueSubtitle('delete', null, 0)).toBe('Delete · no table · 0 keys');
    });

    it('cuts a table name longer than the caption limit to end in an ellipsis', () => {
        expect(keyValueCaption('write', 'Very very long table name', 2)).toBe('Write · Very very long tabl… · 2 keys');
        expect(keyValueCaption('read', 'x'.repeat(CAPTION_TABLE_NAME_LIMIT), 1)).toBe(
            `Read · ${'x'.repeat(CAPTION_TABLE_NAME_LIMIT)} · 1 key`
        );
        expect(keyValueCaption('delete', null, 0)).toBe('Delete · no table · 0 keys');
    });
});
