import { StorageUploadLimits } from '../models/storage.models';
import { describeUploadLimits, isArchiveForLimits, uploadLimitFor, usableUploadLimits } from './upload-limits.utils';

const MB = 1024 * 1024;

const LIMITS: StorageUploadLimits = {
    max_file_size: 500 * MB,
    max_archive_size: 50 * MB,
    free_bytes: 0,
    archive_suffixes: ['.tar', '.tar.bz2', '.tar.gz', '.tar.xz', '.taz', '.tbz', '.tbz2', '.tgz', '.txz', '.zip'],
    document_extensions: ['.docx', '.epub', '.jar', '.xlsx'],
};

/** A response as an older backend sends it, without `key`. */
function without(key: 'archive_suffixes' | 'document_extensions'): StorageUploadLimits {
    const legacy: Partial<StorageUploadLimits> = { ...LIMITS };
    delete legacy[key];
    return legacy as StorageUploadLimits;
}

describe('isArchiveForLimits', () => {
    it.each(['bundle.zip', 'bundle.ZIP', 'x.tar.gz', 'x.tgz', 'x.txz', 'x.tbz', 'x.tbz2', 'x.taz', 'x.tar'])(
        'treats %s as an archive',
        (name) => {
            expect(isArchiveForLimits(name, LIMITS)).toBe(true);
        }
    );

    it.each(['x.sql.gz', 'passwords.txt.gz', 'x.bz2', 'x.xz', 'report.docx', 'book.EPUB', 'notes.txt', 'zip'])(
        'treats %s as a plain file',
        (name) => {
            expect(isArchiveForLimits(name, LIMITS)).toBe(false);
        }
    );

    it('lets a document extension win over an archive suffix it also ends with', () => {
        const limits: StorageUploadLimits = {
            ...LIMITS,
            archive_suffixes: ['.zip'],
            document_extensions: ['.pack.zip'],
        };
        expect(isArchiveForLimits('model.pack.zip', limits)).toBe(false);
        expect(isArchiveForLimits('model.zip', limits)).toBe(true);
    });
});

describe('uploadLimitFor', () => {
    it('uses the archive cap for archives and the file cap otherwise', () => {
        expect(uploadLimitFor('x.tar.gz', LIMITS)).toBe(50 * MB);
        expect(uploadLimitFor('x.txz', LIMITS)).toBe(50 * MB);
        expect(uploadLimitFor('x.sql.gz', LIMITS)).toBe(500 * MB);
        expect(uploadLimitFor('x.docx', LIMITS)).toBe(500 * MB);
    });

    it('is null for a plain file when plain files are not capped', () => {
        expect(uploadLimitFor('report.pdf', { ...LIMITS, max_file_size: null })).toBeNull();
    });
});

describe('usableUploadLimits', () => {
    it('keeps a response that carries both lists', () => {
        expect(usableUploadLimits(LIMITS)).toBe(LIMITS);
    });

    it('drops a missing response or one from a backend without the lists', () => {
        expect(usableUploadLimits(null)).toBeNull();
        expect(usableUploadLimits(undefined)).toBeNull();
        expect(usableUploadLimits(without('archive_suffixes'))).toBeNull();
        expect(usableUploadLimits(without('document_extensions'))).toBeNull();
    });
});

describe('describeUploadLimits', () => {
    it('sizes the caps the way the dialogs size their files', () => {
        expect(describeUploadLimits(LIMITS)).toBe('Max file size: 500.0 MB · Max archive size: 50.0 MB');
        expect(describeUploadLimits({ ...LIMITS, max_file_size: 2 * 1024 * MB })).toBe(
            'Max file size: 2.0 GB · Max archive size: 50.0 MB'
        );
    });

    it('leaves out an uncapped file size', () => {
        expect(describeUploadLimits({ ...LIMITS, max_file_size: null })).toBe('Max archive size: 50.0 MB');
    });

    it('is null when the limits are unknown', () => {
        expect(describeUploadLimits(null)).toBeNull();
        expect(describeUploadLimits(without('archive_suffixes'))).toBeNull();
    });
});
