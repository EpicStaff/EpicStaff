import {
    CAPTION_TABLE_NAME_LIMIT,
    PERSISTENCE_MODE_LABELS,
    persistenceCaption,
    persistenceSubtitle,
} from './persistence-mode-visuals';

describe('persistence mode visuals', () => {
    it('gives every mode a word', () => {
        expect(PERSISTENCE_MODE_LABELS).toEqual({ read: 'Read', write: 'Write', delete: 'Delete' });
    });

    it('formats the subtitle', () => {
        expect(persistenceSubtitle('write', 'customers', 3)).toBe('Write · customers · 3 keys');
        expect(persistenceSubtitle('read', 'customers', 1)).toBe('Read · customers · 1 key');
        expect(persistenceSubtitle('delete', null, 0)).toBe('Delete · no table · 0 keys');
    });

    it('cuts a table name longer than the caption limit to end in an ellipsis', () => {
        expect(persistenceCaption('write', 'Very very long table name', 2)).toBe(
            'Write · Very very long tabl… · 2 keys'
        );
        expect(persistenceCaption('read', 'x'.repeat(CAPTION_TABLE_NAME_LIMIT), 1)).toBe(
            `Read · ${'x'.repeat(CAPTION_TABLE_NAME_LIMIT)} · 1 key`
        );
        expect(persistenceCaption('delete', null, 0)).toBe('Delete · no table · 0 keys');
    });
});
