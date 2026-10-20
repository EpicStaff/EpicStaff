import { OverlayContainer } from '@angular/cdk/overlay';
import { Component, input, signal } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { ConfirmationDialogService } from '@shared/components';
import { Observable, of, Subject } from 'rxjs';

import { PermissionsService } from '../../../../../../services/auth/permissions.service';
import { ToastService } from '../../../../../../services/notifications';
import { CollectionStatus, CreateCollectionDtoResponse } from '../../../../models/collection.model';
import { CollectionDocument, DisplayedListDocument } from '../../../../models/document.model';
import { CollectionsStorageService } from '../../../../services/collections-storage.service';
import { DocumentsApiService } from '../../../../services/documents-api.service';
import { DocumentsStorageService } from '../../../../services/documents-storage.service';
import { CollectionDetailsComponent } from './collection-details.component';
import { CollectionRagsComponent } from './collection-rags/collection-rags.component';

function collection(collectionId: number, collectionName: string): CreateCollectionDtoResponse {
    return {
        collection_id: collectionId,
        collection_name: collectionName,
        description: null,
        status: CollectionStatus.COMPLETED,
        document_count: 0,
        rag_configurations: [],
        created_at: '2026-03-12T13:28:23Z',
        updated_at: '2026-03-12T13:28:23Z',
        created_by: null,
        last_edited_by: null,
        last_edited_at: null,
    };
}

function storedDocument(documentId: number, fileName: string, collectionId = 7): CollectionDocument {
    const fileType = fileName.split('.').pop() as CollectionDocument['file_type'];
    return {
        document_id: documentId,
        file_name: fileName,
        file_size: 1024,
        file_type: fileType,
        source_collection: collectionId,
    };
}

/** The RAG list has its own wide set of dependencies and plays no part here. */
@Component({ selector: 'app-collection-details-rags', template: '' })
class RagsStubComponent {
    readonly collection = input.required<CreateCollectionDtoResponse>();
}

interface Page {
    fixture: ComponentFixture<CollectionDetailsComponent>;
    host: HTMLElement;
    overlay: HTMLElement;
    selectedCollectionId: ReturnType<typeof signal<number | null>>;
    documents: ReturnType<typeof signal<CollectionDocument[]>>;
    update: ReturnType<typeof vi.fn>;
    /** Collection loads answered by the test; the page shows its spinner until then. */
    loads: Subject<CreateCollectionDtoResponse>[];
    render: () => void;
}

function renderPage(): Page {
    const selectedCollectionId = signal<number | null>(null);
    const fullCollections = signal([collection(7, 'CoreStack'), collection(8, 'Echo Library')]);
    const documents = signal<CollectionDocument[]>([
        storedDocument(1, 'a.pdf'),
        storedDocument(2, 'b.txt'),
        storedDocument(3, 'c.pdf'),
        storedDocument(4, 'd.pdf', 8),
    ]);
    const loads: Subject<CreateCollectionDtoResponse>[] = [];
    const update = vi.fn(
        (id: number, body: Partial<CreateCollectionDtoResponse>): Observable<CreateCollectionDtoResponse> =>
            of({ ...collection(id, ''), ...body })
    );
    TestBed.configureTestingModule({
        providers: [
            { provide: PermissionsService, useValue: { can: () => true } },
            { provide: ToastService, useValue: { success: vi.fn(), error: vi.fn() } },
            { provide: ConfirmationDialogService, useValue: {} },
            { provide: DocumentsApiService, useValue: {} },
            {
                provide: CollectionsStorageService,
                useValue: {
                    selectedCollectionId,
                    fullCollections,
                    collections: signal([]),
                    updateCollectionById: update,
                    getFullCollection: () => {
                        const load = new Subject<CreateCollectionDtoResponse>();
                        loads.push(load);
                        return load;
                    },
                },
            },
            {
                provide: DocumentsStorageService,
                useValue: {
                    documents,
                    uploadingDocuments: signal<DisplayedListDocument[]>([]),
                    getDocumentsByCollectionId: () => of(null),
                    isDeleting: () => false,
                },
            },
        ],
    });
    TestBed.overrideComponent(CollectionDetailsComponent, {
        remove: { imports: [CollectionRagsComponent] },
        add: { imports: [RagsStubComponent] },
    });
    const fixture = TestBed.createComponent(CollectionDetailsComponent);
    return {
        fixture,
        host: fixture.nativeElement as HTMLElement,
        overlay: TestBed.inject(OverlayContainer).getContainerElement(),
        selectedCollectionId,
        documents,
        update,
        loads,
        render: () => fixture.detectChanges(),
    };
}

/** Selects the collection and answers its load, so the page shows it. */
function select(page: Page, collectionId: number): void {
    page.selectedCollectionId.set(collectionId);
    page.render();
    const load = page.loads.at(-1)!;
    load.next(collection(collectionId, ''));
    load.complete();
    page.render();
}

function fileNames(page: Page): string[] {
    return Array.from(page.host.querySelectorAll('.files__name')).map((name) => name.textContent?.trim() ?? '');
}

function filterLabel(page: Page): string {
    return page.host.querySelector('.details__file-type-filter .selector__text')?.textContent?.trim() ?? '';
}

function chooseFileType(page: Page, label: string): void {
    page.host.querySelector<HTMLButtonElement>('.details__file-type-filter button')!.click();
    page.render();
    const option = Array.from(page.overlay.querySelectorAll<HTMLElement>('.selector__option')).find(
        (candidate) => candidate.textContent?.trim() === label
    );
    option!.click();
    page.render();
}

describe('CollectionDetailsComponent filter by type', () => {
    it('offers the types of the collection and lists only the files of the chosen one', () => {
        const page = renderPage();
        select(page, 7);

        expect(filterLabel(page)).toBe('Filter by type');
        expect(fileNames(page)).toEqual(['a.pdf', 'b.txt', 'c.pdf']);

        chooseFileType(page, '.pdf');

        expect(filterLabel(page)).toBe('.pdf');
        expect(fileNames(page)).toEqual(['a.pdf', 'c.pdf']);

        chooseFileType(page, 'All types');

        expect(filterLabel(page)).toBe('Filter by type');
        expect(fileNames(page)).toEqual(['a.pdf', 'b.txt', 'c.pdf']);
    });

    it('opens every collection unfiltered', () => {
        const page = renderPage();
        select(page, 7);
        chooseFileType(page, '.pdf');

        select(page, 8);

        expect(filterLabel(page)).toBe('Filter by type');
        expect(fileNames(page)).toEqual(['d.pdf']);
    });

    it('clears the filter when the last file of its type goes, and does not bring it back later', () => {
        const page = renderPage();
        select(page, 7);
        chooseFileType(page, '.txt');

        page.documents.update((documents) => documents.filter((document) => document.file_type !== 'txt'));
        page.render();
        expect(filterLabel(page)).toBe('Filter by type');

        page.documents.update((documents) => [...documents, storedDocument(5, 'e.txt')]);
        page.render();

        expect(filterLabel(page)).toBe('Filter by type');
        expect(fileNames(page)).toEqual(['a.pdf', 'c.pdf', 'e.txt']);
    });
});

describe('CollectionDetailsComponent collection name autosave', () => {
    beforeEach(() => vi.useFakeTimers());
    afterEach(() => vi.useRealTimers());

    it('saves a name typed just before switching to the collection that was being edited', () => {
        const page = renderPage();
        select(page, 7);
        const name = page.host.querySelector<HTMLInputElement>('input#collection-name')!;
        name.value = 'CoreStack v2';
        name.dispatchEvent(new Event('input'));

        // The next collection is still loading, so the spinner replaces (destroys) the Basics editor.
        page.selectedCollectionId.set(8);
        page.render();

        expect(page.host.querySelector('app-collection-basics')).toBeNull();
        expect(page.update).toHaveBeenCalledExactlyOnceWith(7, { collection_name: 'CoreStack v2' });
    });
});
