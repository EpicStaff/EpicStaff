import { Dialog } from '@angular/cdk/dialog';
import { TestBed } from '@angular/core/testing';
import { of, Subject, throwError } from 'rxjs';

import { ToastService } from '../../../services/notifications';
import { CreateCollectionDialogComponent } from '../components/create-collection-dialog/create-collection-dialog.component';
import { CreateCollectionDtoResponse } from '../models/collection.model';
import { StorageImportCandidate } from '../models/document.model';
import { CollectionCreationService } from './collection-creation.service';
import { CollectionsStorageService } from './collections-storage.service';
import { DocumentsStorageService } from './documents-storage.service';

const created = { collection_id: 12 } as CreateCollectionDtoResponse;

function fileList(...files: File[]): FileList {
    return files as unknown as FileList;
}

describe('CollectionCreationService', () => {
    let service: CollectionCreationService;
    let createRequest: Subject<CreateCollectionDtoResponse>;
    let wizardClosed: Subject<void>;
    let dialog: { open: ReturnType<typeof vi.fn> };
    let collectionsStorage: {
        createCollection: ReturnType<typeof vi.fn>;
        setSelectedCollectionId: ReturnType<typeof vi.fn>;
        getFullCollection: ReturnType<typeof vi.fn>;
    };
    let documentsStorage: {
        registerNewCollection: ReturnType<typeof vi.fn>;
        importFromStorage: ReturnType<typeof vi.fn>;
        uploadDocuments: ReturnType<typeof vi.fn>;
    };
    let toast: {
        success: ReturnType<typeof vi.fn>;
        warning: ReturnType<typeof vi.fn>;
        error: ReturnType<typeof vi.fn>;
    };

    beforeEach(() => {
        createRequest = new Subject();
        wizardClosed = new Subject();
        dialog = { open: vi.fn(() => ({ closed: wizardClosed })) };
        collectionsStorage = {
            createCollection: vi.fn(() => createRequest),
            setSelectedCollectionId: vi.fn(),
            getFullCollection: vi.fn(() => of(null)),
        };
        documentsStorage = {
            registerNewCollection: vi.fn(),
            importFromStorage: vi.fn(() => of(null)),
            uploadDocuments: vi.fn(() => of(undefined)),
        };
        toast = { success: vi.fn(), warning: vi.fn(), error: vi.fn() };

        TestBed.configureTestingModule({
            providers: [
                { provide: Dialog, useValue: dialog },
                { provide: CollectionsStorageService, useValue: collectionsStorage },
                { provide: DocumentsStorageService, useValue: documentsStorage },
                { provide: ToastService, useValue: toast },
            ],
        });
        service = TestBed.inject(CollectionCreationService);
    });

    function respond(): void {
        createRequest.next(created);
        createRequest.complete();
    }

    it('creates a collection, selects it and opens the wizard on it', () => {
        service.createCollection();
        expect(service.isCreating()).toBe(true);

        respond();

        expect(service.isCreating()).toBe(false);
        expect(documentsStorage.registerNewCollection).toHaveBeenCalledWith(12);
        expect(collectionsStorage.setSelectedCollectionId).toHaveBeenCalledWith(12);
        expect(dialog.open).toHaveBeenCalledWith(
            CreateCollectionDialogComponent,
            expect.objectContaining({ data: { collection_id: 12 }, disableClose: true })
        );
    });

    it('reloads the collection once the wizard closes', () => {
        service.createCollection();
        respond();
        expect(collectionsStorage.getFullCollection).not.toHaveBeenCalled();

        wizardClosed.next();

        expect(collectionsStorage.getFullCollection).toHaveBeenCalledWith(12, true);
    });

    it('starts one creation at a time', () => {
        service.createCollection();
        service.createCollection();

        expect(collectionsStorage.createCollection).toHaveBeenCalledTimes(1);
    });

    it('toasts a failed create and opens nothing', () => {
        collectionsStorage.createCollection.mockReturnValue(throwError(() => new Error('boom')));

        service.createCollection();

        expect(toast.error).toHaveBeenCalledWith('Failed to create collection');
        expect(dialog.open).not.toHaveBeenCalled();
        expect(service.isCreating()).toBe(false);
    });

    describe('from storage items', () => {
        const items: StorageImportCandidate[] = [
            { id: 5, name: 'report.pdf', type: 'file' },
            { id: 6, name: 'raw', type: 'folder' },
        ];

        it('imports the items into the new collection before the wizard shows it', () => {
            service.createCollectionFromStorage(items);
            respond();

            expect(documentsStorage.importFromStorage).toHaveBeenCalledWith(12, items);
            expect(documentsStorage.registerNewCollection.mock.invocationCallOrder[0]).toBeLessThan(
                documentsStorage.importFromStorage.mock.invocationCallOrder[0]
            );
            expect(dialog.open).toHaveBeenCalledTimes(1);
        });

        it('creates nothing when no item can be imported', () => {
            service.createCollectionFromStorage([{ id: null, name: 'virtual', type: 'folder' }]);

            expect(toast.error).toHaveBeenCalledWith('None of the selected items could be added');
            expect(collectionsStorage.createCollection).not.toHaveBeenCalled();
        });
    });

    describe('from computer files', () => {
        const notes = new File(['a'], 'notes.md');
        const report = new File(['b'], 'report.pdf');
        const binary = new File(['c'], 'tool.exe');

        it('uploads the files into the new collection, showing them as uploading meanwhile', () => {
            service.createCollectionFromFiles(fileList(notes, report));
            respond();

            expect(documentsStorage.uploadDocuments).toHaveBeenCalledWith(
                12,
                [notes, report],
                [
                    expect.objectContaining({ file_name: 'notes.md', source_collection: 12 }),
                    expect.objectContaining({ file_name: 'report.pdf', source_collection: 12 }),
                ]
            );
            expect(dialog.open).toHaveBeenCalledTimes(1);
            expect(toast.warning).not.toHaveBeenCalled();
        });

        it('skips files a collection does not take, and same-name files after the first', () => {
            service.createCollectionFromFiles(fileList(notes, binary, new File(['d'], 'notes.md')));
            respond();

            expect(toast.warning).toHaveBeenCalledWith('1 file(s) skipped: unsupported type or too large');
            expect(documentsStorage.uploadDocuments).toHaveBeenCalledWith(12, [notes], expect.any(Array));
        });

        it('creates nothing when no file can be added', () => {
            service.createCollectionFromFiles(fileList(binary));

            expect(toast.error).toHaveBeenCalledWith(
                'None of the dropped files could be added: unsupported type or too large'
            );
            expect(collectionsStorage.createCollection).not.toHaveBeenCalled();
        });
    });
});
