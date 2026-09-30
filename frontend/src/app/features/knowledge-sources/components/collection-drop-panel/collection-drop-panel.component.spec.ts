// Side-effect import: DocumentsStorageService's dependency graph reaches shared/utils/http-error.util.ts,
// which reads the `validationErrors` augmentation declared by this interceptor module.
import '../../../../core/interceptors/validation-errors.interceptor';

import { signal } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { ActionCode, ResourceCode } from '@shared/models';
import { of, Subject } from 'rxjs';

import { PermissionsService } from '../../../../services/auth/permissions.service';
import { ToastService } from '../../../../services/notifications';
import { CollectionStatus, GetCollectionRequest } from '../../models/collection.model';
import { ImportFromStorageResponse, StorageImportCandidate } from '../../models/document.model';
import { CollectionsApiService } from '../../services/collections-api.service';
import { CollectionsStorageService } from '../../services/collections-storage.service';
import { DocumentsApiService } from '../../services/documents-api.service';
import { CollectionDropPanelComponent } from './collection-drop-panel.component';

function collection(id: number, name: string): GetCollectionRequest {
    return {
        collection_id: id,
        collection_name: name,
        description: null,
        user_id: '1',
        status: CollectionStatus.COMPLETED,
        document_count: 2,
        rag_configurations: [],
        created_at: '2026-01-01T00:00:00Z',
        updated_at: '2026-01-01T00:00:00Z',
    };
}

describe('CollectionDropPanelComponent', () => {
    let fixture: ComponentFixture<CollectionDropPanelComponent>;
    let granted: Set<string>;
    let collectionsStorage: {
        collections: ReturnType<typeof signal<GetCollectionRequest[]>>;
        isCollectionsLoaded: ReturnType<typeof signal<boolean>>;
        getCollections: ReturnType<typeof vi.fn>;
        getFullCollection: ReturnType<typeof vi.fn>;
    };
    let pendingImport: Subject<ImportFromStorageResponse>;
    let documentsApi: { importFromStorage: ReturnType<typeof vi.fn> };
    let toast: {
        success: ReturnType<typeof vi.fn>;
        warning: ReturnType<typeof vi.fn>;
        error: ReturnType<typeof vi.fn>;
    };

    const draggedItems: StorageImportCandidate[] = [
        { id: 5, name: 'report.pdf', type: 'file', size: 1000 },
        { id: 6, name: 'raw', type: 'folder' },
        { id: 7, name: 'tool.exe', type: 'file', size: 1000 },
    ];

    function grant(resource: ResourceCode, action: ActionCode): void {
        granted.add(`${resource}:${action}`);
    }

    function setUp(options: { active?: boolean } = {}): void {
        TestBed.configureTestingModule({
            imports: [CollectionDropPanelComponent],
            providers: [
                {
                    provide: PermissionsService,
                    useValue: {
                        can: (resource: ResourceCode, action: ActionCode) => granted.has(`${resource}:${action}`),
                    },
                },
                { provide: CollectionsStorageService, useValue: collectionsStorage },
                { provide: CollectionsApiService, useValue: {} },
                { provide: DocumentsApiService, useValue: documentsApi },
                { provide: ToastService, useValue: toast },
            ],
        });
        fixture = TestBed.createComponent(CollectionDropPanelComponent);
        fixture.componentRef.setInput('items', draggedItems);
        fixture.componentRef.setInput('active', options.active ?? true);
        fixture.detectChanges();
    }

    function host(): HTMLElement {
        return fixture.nativeElement as HTMLElement;
    }

    function row(collectionId: number): HTMLElement {
        return host().querySelector(`[data-collection-id="${collectionId}"]`) as HTMLElement;
    }

    function drop(collectionId: number): void {
        row(collectionId).dispatchEvent(new Event('drop', { bubbles: true, cancelable: true }));
    }

    beforeEach(() => {
        granted = new Set();
        grant(ResourceCode.KnowledgeSources, ActionCode.Create);
        grant(ResourceCode.KnowledgeSources, ActionCode.Read);
        grant(ResourceCode.Files, ActionCode.Read);
        collectionsStorage = {
            collections: signal([collection(1, 'Specs'), collection(2, 'Manuals')]),
            isCollectionsLoaded: signal(false),
            getCollections: vi.fn(() => {
                collectionsStorage.isCollectionsLoaded.set(true);
                return of([]);
            }),
            getFullCollection: vi.fn(() => of(null)),
        };
        pendingImport = new Subject();
        documentsApi = { importFromStorage: vi.fn(() => pendingImport) };
        toast = { success: vi.fn(), warning: vi.fn(), error: vi.fn() };
    });

    it('renders one drop target per collection while a drag is active', () => {
        setUp();

        expect(row(1)?.textContent).toContain('Specs');
        expect(row(2)?.textContent).toContain('Manuals');
    });

    it('loads collections lazily, the first time it becomes visible, and only once', () => {
        setUp({ active: false });
        expect(collectionsStorage.getCollections).not.toHaveBeenCalled();

        fixture.componentRef.setInput('active', true);
        fixture.detectChanges();
        fixture.componentRef.setInput('active', false);
        fixture.detectChanges();
        fixture.componentRef.setInput('active', true);
        fixture.detectChanges();

        expect(collectionsStorage.getCollections).toHaveBeenCalledTimes(1);
    });

    it('shows the advisory pre-check for files that will likely be skipped', () => {
        setUp();

        expect(host().textContent).toContain('1 file(s) may be skipped');
    });

    it('renders nothing when no drag is active', () => {
        setUp({ active: false });

        expect(row(1)).toBeNull();
    });

    it.each([
        [ResourceCode.KnowledgeSources, ActionCode.Create],
        [ResourceCode.KnowledgeSources, ActionCode.Read],
        [ResourceCode.Files, ActionCode.Read],
    ])('stays hidden and loads nothing without %s %s', (resource, action) => {
        granted.delete(`${resource}:${action}`);
        setUp();

        expect(row(1)).toBeNull();
        expect(collectionsStorage.getCollections).not.toHaveBeenCalled();
    });

    it('imports every dragged id into the collection it was dropped on', () => {
        setUp();

        drop(2);

        expect(documentsApi.importFromStorage).toHaveBeenCalledWith(2, [5, 6, 7]);
    });

    it('keeps the import running after the panel is destroyed and still toasts the result', () => {
        setUp();
        drop(1);
        expect(pendingImport.observed).toBe(true);

        fixture.destroy();

        expect(pendingImport.observed).toBe(true);
        pendingImport.next({ message: 'ok', documents: [], skipped: [] });
        pendingImport.complete();
        expect(toast.warning).toHaveBeenCalledWith('0 documents imported');
    });

    it('marks the row busy while importing and ignores a second drop on it', () => {
        setUp();
        drop(1);
        fixture.detectChanges();

        expect(row(1).classList).toContain('collection-drop-panel__row--importing');
        drop(1);
        expect(documentsApi.importFromStorage).toHaveBeenCalledTimes(1);
    });

    it('highlights the hovered row and accepts the drop as a copy', () => {
        setUp();
        const dragOver = new Event('dragover', { bubbles: true, cancelable: true });

        row(1).dispatchEvent(dragOver);
        fixture.detectChanges();

        expect(dragOver.defaultPrevented).toBe(true);
        expect(row(1).classList).toContain('collection-drop-panel__row--hovered');
        expect(row(2).classList).not.toContain('collection-drop-panel__row--hovered');
    });

    it('does not call the API when no dragged item has a storage id', () => {
        setUp();
        fixture.componentRef.setInput('items', [{ id: null, name: 'ghost.txt', type: 'file' }]);
        fixture.detectChanges();

        drop(1);

        expect(documentsApi.importFromStorage).not.toHaveBeenCalled();
        expect(toast.error).toHaveBeenCalledWith('None of the selected items could be added');
    });
});
