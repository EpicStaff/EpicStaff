import {
    buildCollectionStats,
    collectFileTypes,
    CollectionStatsDocument,
    formatCollectionSize,
    formatFileTypes,
    NO_FILE_TYPES,
} from './collection-stats.util';

const KB = 1024;

const STORED: CollectionStatsDocument[] = [
    { document_id: 1, file_type: 'txt', file_size: 10 * KB },
    { document_id: 2, file_type: 'pdf', file_size: 1.5 * KB },
    { document_id: 3, file_type: 'pdf', file_size: 3 * KB * KB },
];
const UPLOADING: CollectionStatsDocument = { file_size: 50 * KB * KB };
const REJECTED: CollectionStatsDocument = { file_type: 'exe', file_size: 7 };

describe('formatCollectionSize', () => {
    it('formats bytes in the largest whole unit, dropping decimals from whole values', () => {
        expect(formatCollectionSize(0)).toBe('0 B');
        expect(formatCollectionSize(512)).toBe('512 B');
        expect(formatCollectionSize(10 * KB)).toBe('10 KB');
        expect(formatCollectionSize(1.5 * KB)).toBe('1.5 KB');
        expect(formatCollectionSize(3 * KB * KB)).toBe('3 MB');
    });
});

describe('collectFileTypes', () => {
    it('returns the distinct types of the stored documents, alphabetical', () => {
        expect(collectFileTypes([...STORED, UPLOADING, REJECTED])).toEqual(['pdf', 'txt']);
    });
});

describe('formatFileTypes', () => {
    it('lists the types as dotted extensions', () => {
        expect(formatFileTypes(['pdf', 'txt'])).toBe('.pdf, .txt');
    });

    it('shows a dash when there are none', () => {
        expect(formatFileTypes([])).toBe(NO_FILE_TYPES);
    });
});

describe('buildCollectionStats', () => {
    it('counts, types and sizes the stored documents', () => {
        expect(buildCollectionStats(STORED)).toEqual({
            fileCount: 3,
            fileTypes: ['pdf', 'txt'],
            totalSize: formatCollectionSize(10 * KB + 1.5 * KB + 3 * KB * KB),
            largestFileSize: '3 MB',
            smallestFileSize: '1.5 KB',
        });
    });

    it('leaves out uploads in flight and rejected files, which are not in the collection', () => {
        expect(buildCollectionStats([...STORED, UPLOADING, REJECTED])).toEqual(buildCollectionStats(STORED));
    });

    it('reports an empty collection as zero files of zero size', () => {
        expect(buildCollectionStats([])).toEqual({
            fileCount: 0,
            fileTypes: [],
            totalSize: '0 B',
            largestFileSize: '0 B',
            smallestFileSize: '0 B',
        });
    });

    it('treats a single file as both the largest and the smallest', () => {
        const stats = buildCollectionStats([STORED[0]]);

        expect(stats.largestFileSize).toBe('10 KB');
        expect(stats.smallestFileSize).toBe('10 KB');
    });
});
