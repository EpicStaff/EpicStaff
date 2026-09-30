// Side-effect import: http-error.util.ts reads the `validationErrors` augmentation declared here.
import '../../../core/interceptors/validation-errors.interceptor';

import { HttpErrorResponse } from '@angular/common/http';
import { TestBed } from '@angular/core/testing';
import { of, Subject, throwError } from 'rxjs';

import { ToastService } from '../../../services/notifications';
import { ImportFromStorageResponse, StorageImportCandidate } from '../models/document.model';
import { CollectionsApiService } from './collections-api.service';
import { CollectionsStorageService } from './collections-storage.service';
import { DocumentsApiService } from './documents-api.service';
import { DocumentsStorageService } from './documents-storage.service';

function candidate(id: number | null): StorageImportCandidate {
    return { id, name: `file-${id}.pdf`, type: 'file' };
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

    it('adds the 400 skipped reasons to the error toast', () => {
        documentsApi.importFromStorage.mockReturnValue(
            throwError(
                () =>
                    new HttpErrorResponse({
                        status: 400,
                        error: {
                            error: 'Nothing to import',
                            skipped: [
                                { storage_file_id: 1, path: 'a.exe', reason: 'unsupported_type' },
                                { storage_file_id: 2, path: 'b.pdf', reason: 'too_large' },
                            ],
                        },
                    })
            )
        );

        importResult();

        expect(toast.error).toHaveBeenCalledWith('Nothing to import (skipped: 1 unsupported type, 1 too large)');
    });

    it('shows the standard message of a 404', () => {
        documentsApi.importFromStorage.mockReturnValue(
            throwError(
                () =>
                    new HttpErrorResponse({
                        status: 404,
                        error: { status_code: 404, code: 'not_found', message: 'Storage file 9 not found' },
                    })
            )
        );

        importResult();

        expect(toast.error).toHaveBeenCalledWith('Storage file 9 not found');
    });

    it('shows the server error text of a 400 and emits null', () => {
        documentsApi.importFromStorage.mockReturnValue(
            throwError(
                () =>
                    new HttpErrorResponse({
                        status: 400,
                        error: { error: 'No importable files', skipped: [] },
                    })
            )
        );

        expect(importResult()).toBeNull();
        expect(toast.error).toHaveBeenCalledWith('No importable files');
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
        pending.error(new HttpErrorResponse({ status: 500, error: { error: 'boom' } }));

        expect(service.isImporting(4)).toBe(false);
        expect(toast.error).toHaveBeenCalledWith('boom');
    });
});
