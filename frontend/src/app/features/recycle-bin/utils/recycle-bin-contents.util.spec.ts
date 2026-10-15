import {
    documentFormatGroup,
    FOLDER_FORMAT_GROUP,
    NO_EXTENSION_FORMAT_GROUP,
    storageFormatGroup,
} from './recycle-bin-contents.util';

describe('storageFormatGroup', () => {
    it.each([
        ['report.pdf', 'file', 'PDF'],
        ['sub/notes.md', 'file', 'MD'],
        ['data.backup.json', 'file', 'JSON'],
        ['Makefile', 'file', NO_EXTENSION_FORMAT_GROUP],
        ['.env', 'file', NO_EXTENSION_FORMAT_GROUP],
        ['sub/', 'folder', FOLDER_FORMAT_GROUP],
    ])('puts %s (%s) in %s', (name, nodeType, group) => {
        expect(storageFormatGroup({ name, nodeType })).toBe(group);
    });

    it('groups a collection document by its format, never as a folder', () => {
        expect(documentFormatGroup({ name: 'manual.pdf', nodeType: 'document' })).toBe('PDF');
        expect(documentFormatGroup({ name: 'notes.docx', nodeType: 'document' })).toBe('DOCX');
        expect(documentFormatGroup({ name: 'README', nodeType: 'document' })).toBe(NO_EXTENSION_FORMAT_GROUP);
    });
});
