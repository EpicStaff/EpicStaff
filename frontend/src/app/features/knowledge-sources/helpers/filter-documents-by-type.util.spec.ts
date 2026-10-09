import { DisplayedListDocument } from '../models/document.model';
import { filterDocumentsByType } from './filter-documents-by-type.util';

function document(overrides: Partial<DisplayedListDocument>): DisplayedListDocument {
    return {
        file_name: 'file',
        file_size: 1,
        source_collection: 1,
        isValidType: true,
        isValidSize: true,
        ...overrides,
    };
}

const PDF = document({ document_id: 1, file_name: 'a.pdf', file_type: 'pdf' });
const TXT = document({ document_id: 2, file_name: 'b.txt', file_type: 'txt' });
const SECOND_PDF = document({ document_id: 3, file_name: 'c.pdf', file_type: 'pdf' });
const UPLOADING = document({ file_name: 'd.txt' });
const REJECTED = document({ file_name: 'e.exe', isValidType: false });
const ALL = [PDF, TXT, SECOND_PDF, UPLOADING, REJECTED];

describe('filterDocumentsByType', () => {
    it('keeps only the stored documents of the chosen type', () => {
        expect(filterDocumentsByType([PDF, TXT, SECOND_PDF], 'pdf')).toEqual([PDF, SECOND_PDF]);
    });

    it('returns every document, unchanged, for "all types"', () => {
        expect(filterDocumentsByType(ALL, null)).toBe(ALL);
    });

    it('restores the full list when the filter goes back to "all types"', () => {
        expect(filterDocumentsByType(ALL, 'txt')).toEqual([TXT, UPLOADING, REJECTED]);
        expect(filterDocumentsByType(ALL, null)).toEqual(ALL);
    });

    it('never hides uploads in flight or rejected files', () => {
        expect(filterDocumentsByType(ALL, 'pdf')).toEqual([PDF, SECOND_PDF, UPLOADING, REJECTED]);
    });

    it('does not modify the given list', () => {
        const documents = [...ALL];

        filterDocumentsByType(documents, 'pdf');

        expect(documents).toEqual(ALL);
    });
});
