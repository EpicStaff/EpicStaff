// Side-effect import: http-error.util.ts reads the `validationErrors` augmentation declared here.
import '../../../core/interceptors/validation-errors.interceptor';

import { HttpErrorResponse } from '@angular/common/http';
import { TestBed } from '@angular/core/testing';
import { of, Subject, throwError } from 'rxjs';

import { ToastService } from '../../../services/notifications';
import {
    ImportFromStorageErrorResponse,
    ImportFromStorageResponse,
    StorageImportCandidate,
} from '../models/document.model';
import { CollectionsApiService } from './collections-api.service';
import { CollectionsStorageService } from './collections-storage.service';
import { DocumentsApiService } from './documents-api.service';
import { DocumentsStorageService } from './documents-storage.service';

function candidate(id: number | null): StorageImportCandidate {
    return { id, name: `file-${id}.pdf`, type: 'file' };
}

/** The project error envelope the import endpoint sends for every 4xx. */
function errorEnvelope(
    status: number,
    code: string,
    message: string,
    extra: Partial<ImportFromStorageErrorResponse> = {}
): HttpErrorResponse {
    const error: ImportFromStorageErrorResponse = { status_code: status, code, message, ...extra };
    return new HttpErrorResponse({ status, error });
}

describe('DocumentsStorageService.importFromStorage', () => {
    let service: DocumentsStorageService;
    let documentsApi: { importFromStorage: ReturnType<typeof vi.fn> };
    let collectionsStorage: {
        getFullCollection: ReturnType<typeof vi.fn>;
        updateDocumentCount: ReturnType<typeof vi.fn>;
    };
    let toast: {
        success: ReturnType<typeof vi.fn>;
        warning: ReturnType<typeof vi.fn>;
        error: ReturnType<typeof vi.fn>;
    };

    beforeEach(() => {
        documentsApi = { importFromStorage: vi.fn() };
        collectionsStorage = { getFullCollection: vi.fn(() => of(null)), updateDocumentCount: vi.fn() };
        toast = { success: vi.fn(), warning: vi.fn(), error: vi.fn() };

        TestBed.configureTestingModule({
            providers: [
                { provide: DocumentsApiService, useValue: documentsApi },
                { provide: CollectionsApiService, useValue: {} },
                { provide: CollectionsStorageService, useValue: collectionsStorage },
                { provide: ToastService, useValue: toast },
            ],
        });
        service = TestBed.inject(DocumentsStorageService);
    });

    function importResult(): ImportFromStorageResponse | null | undefined {
        let result: ImportFromStorageResponse | null | undefined;
        service.importFromStorage(4, [candidate(1), candidate(2)]).subscribe((value) => (result = value));
        return result;
    }

    it('toasts the imported and skipped counts and refreshes the collection', () => {
        const response: ImportFromStorageResponse = {
            message: 'ok',
            documents: [{ document_id: 1, file_name: 'a.pdf', file_size: 10, file_type: 'pdf', source_collection: 4 }],
            skipped: [
                { storage_file_id: 2, path: 'b.exe', reason: 'unsupported_type' },
                { storage_file_id: 3, path: 'c.pdf', reason: 'duplicate' },
            ],
        };
        documentsApi.importFromStorage.mockReturnValue(of(response));

        expect(importResult()).toBe(response);
        expect(documentsApi.importFromStorage).toHaveBeenCalledWith(4, [1, 2]);
        expect(toast.warning).toHaveBeenCalledWith(
            '1 document imported, 2 skipped (1 unsupported type, 1 already in the collection)'
        );
        expect(collectionsStorage.getFullCollection).toHaveBeenCalledWith(4, true);
    });

    it('toasts success when documents were imported and nothing was skipped', () => {
        documentsApi.importFromStorage.mockReturnValue(
            of({
                message: 'ok',
                documents: [
                    { document_id: 1, file_name: 'a.pdf', file_size: 10, file_type: 'pdf', source_collection: 4 },
                ],
                skipped: [],
            })
        );

        importResult();

        expect(toast.success).toHaveBeenCalledWith('1 document imported');
    });

    it('warns, not succeeds, when zero documents were imported', () => {
        documentsApi.importFromStorage.mockReturnValue(of({ message: 'ok', documents: [], skipped: [] }));

        importResult();

        expect(toast.warning).toHaveBeenCalledWith('0 documents imported');
        expect(toast.success).not.toHaveBeenCalled();
    });

    it('keeps the request alive after the caller unsubscribes and tracks the importing collection', () => {
        const pending = new Subject<ImportFromStorageResponse>();
        documentsApi.importFromStorage.mockReturnValue(pending);

        const subscription = service.importFromStorage(4, [candidate(1)]).subscribe();
        expect(service.isImporting(4)).toBe(true);
        subscription.unsubscribe();

        expect(pending.observed).toBe(true);
        pending.next({ message: 'ok', documents: [], skipped: [] });
        pending.complete();
        expect(toast.warning).toHaveBeenCalledWith('0 documents imported');
        expect(service.isImporting(4)).toBe(false);
    });

    it('sends only resolvable ids and reports the rest', () => {
        documentsApi.importFromStorage.mockReturnValue(of({ message: 'ok', documents: [], skipped: [] }));

        service.importFromStorage(4, [candidate(1), candidate(null), candidate(3)]).subscribe();

        expect(documentsApi.importFromStorage).toHaveBeenCalledWith(4, [1, 3]);
        expect(toast.warning).toHaveBeenCalledWith('1 item(s) could not be added');
    });

    it('sends nothing when no item has an id', () => {
        let result: ImportFromStorageResponse | null | undefined;
        service.importFromStorage(4, [candidate(null)]).subscribe((value) => (result = value));

        expect(result).toBeNull();
        expect(documentsApi.importFromStorage).not.toHaveBeenCalled();
        expect(toast.error).toHaveBeenCalledWith('None of the selected items could be added');
    });

    it('reports why each file was skipped when nothing could be imported', () => {
        documentsApi.importFromStorage.mockReturnValue(
            throwError(() =>
                errorEnvelope(400, 'nothing_to_import', 'None of the selected storage files can be imported', {
                    skipped: [
                        { storage_file_id: 1, path: 'a.exe', reason: 'unsupported_type' },
                        { storage_file_id: 2, path: 'b.pdf', reason: 'too_large' },
                        { storage_file_id: 3, path: 'c.pdf', reason: 'duplicate' },
                    ],
                })
            )
        );

        expect(importResult()).toBeNull();
        expect(toast.error).toHaveBeenCalledWith(
            'None of the selected storage files can be imported (skipped: 1 unsupported type, 1 too large, 1 already in the collection)'
        );
        expect(collectionsStorage.getFullCollection).not.toHaveBeenCalled();
    });

    it.each([
        {
            case: 'nothing to import, with no file to name',
            status: 400,
            code: 'nothing_to_import',
            message: 'None of the selected storage files can be imported',
            extra: { skipped: [] },
        },
        {
            case: 'a selection over the import limits',
            status: 400,
            code: 'storage_import_limit_exceeded',
            message: 'Too many files selected',
            extra: {},
        },
        {
            case: 'a file the validator rejects',
            status: 400,
            code: 'upload_rejected',
            message: 'report.pdf is corrupted',
            extra: {},
        },
        {
            case: 'another error that carries skipped files',
            status: 400,
            code: 'upload_rejected',
            message: 'report.pdf is corrupted',
            extra: { skipped: [{ storage_file_id: 1, path: 'a.exe', reason: 'unsupported_type' as const }] },
        },
        {
            case: 'a missing collection or storage file',
            status: 404,
            code: 'not_found',
            message: 'Not found.',
            extra: {},
        },
    ])('toasts just the server message for $case and emits null', ({ status, code, message, extra }) => {
        documentsApi.importFromStorage.mockReturnValue(throwError(() => errorEnvelope(status, code, message, extra)));

        expect(importResult()).toBeNull();
        expect(toast.error).toHaveBeenCalledWith(message);
        expect(collectionsStorage.getFullCollection).not.toHaveBeenCalled();
    });

    it('leaves a 403 to the forbidden interceptor instead of toasting twice', () => {
        documentsApi.importFromStorage.mockReturnValue(
            throwError(() => new HttpErrorResponse({ status: 403, error: { message: 'Forbidden' } }))
        );

        expect(importResult()).toBeNull();
        expect(toast.error).not.toHaveBeenCalled();
    });

    it('stays importing until every overlapping import into the same collection has finished', () => {
        const first = new Subject<ImportFromStorageResponse>();
        const second = new Subject<ImportFromStorageResponse>();
        documentsApi.importFromStorage.mockReturnValueOnce(first).mockReturnValueOnce(second);

        service.importFromStorage(4, [candidate(1)]);
        service.importFromStorage(4, [candidate(2)]);

        first.next({ message: 'ok', documents: [], skipped: [] });
        first.complete();
        expect(service.isImporting(4)).toBe(true);

        second.next({ message: 'ok', documents: [], skipped: [] });
        second.complete();
        expect(service.isImporting(4)).toBe(false);
    });

    it('is not importing any more after a failed import', () => {
        const pending = new Subject<ImportFromStorageResponse>();
        documentsApi.importFromStorage.mockReturnValue(pending);

        service.importFromStorage(4, [candidate(1)]);
        expect(service.isImporting(4)).toBe(true);
        pending.error(new HttpErrorResponse({ status: 500 }));

        expect(service.isImporting(4)).toBe(false);
        expect(toast.error).toHaveBeenCalledTimes(1);
    });
});

describe('DocumentsStorageService — imported documents in the document cache', () => {
    let service: DocumentsStorageService;
    let documentsApi: { importFromStorage: ReturnType<typeof vi.fn> };
    let collectionsApi: { getDocumentsByCollectionId: ReturnType<typeof vi.fn> };

    const imported: ImportFromStorageResponse = {
        message: 'ok',
        documents: [{ document_id: 9, file_name: 'a.pdf', file_size: 10, file_type: 'pdf', source_collection: 4 }],
        skipped: [],
    };

    beforeEach(() => {
        documentsApi = { importFromStorage: vi.fn(() => of(imported)) };
        collectionsApi = { getDocumentsByCollectionId: vi.fn(() => of({ documents: [] })) };

        TestBed.configureTestingModule({
            providers: [
                { provide: DocumentsApiService, useValue: documentsApi },
                { provide: CollectionsApiService, useValue: collectionsApi },
                {
                    provide: CollectionsStorageService,
                    useValue: { getFullCollection: vi.fn(() => of(null)), updateDocumentCount: vi.fn() },
                },
                { provide: ToastService, useValue: { success: vi.fn(), warning: vi.fn(), error: vi.fn() } },
            ],
        });
        service = TestBed.inject(DocumentsStorageService);
    });

    function documentIdsOf(collectionId: number): number[] {
        return service
            .documents()
            .filter((document) => document.source_collection === collectionId)
            .map((document) => document.document_id);
    }

    it('shows documents imported into a fetched, empty collection (e.g. the open one)', () => {
        service.getDocumentsByCollectionId(4).subscribe();

        service.importFromStorage(4, [candidate(1)]).subscribe();

        expect(documentIdsOf(4)).toEqual([9]);
    });

    it('does not start a partial cache for a collection whose documents were never fetched', () => {
        service.importFromStorage(4, [candidate(1)]).subscribe();

        expect(documentIdsOf(4)).toEqual([]);
    });

    it('forgets fetched collections on clear', () => {
        service.getDocumentsByCollectionId(4).subscribe();
        service.clear();

        service.importFromStorage(4, [candidate(1)]).subscribe();

        expect(documentIdsOf(4)).toEqual([]);
    });
});
