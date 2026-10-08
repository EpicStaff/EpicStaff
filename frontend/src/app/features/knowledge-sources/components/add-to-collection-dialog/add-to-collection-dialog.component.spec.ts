// Side-effect import: DocumentsStorageService's dependency graph reaches shared/utils/http-error.util.ts,
// which reads the `validationErrors` augmentation declared by this interceptor module.
import '../../../../core/interceptors/validation-errors.interceptor';

import { DIALOG_DATA, DialogRef } from '@angular/cdk/dialog';
import { signal } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { of, Subject } from 'rxjs';

import { CollectionStatus, GetCollectionRequest } from '../../models/collection.model';
import { ImportFromStorageResponse } from '../../models/document.model';
import { CollectionsStorageService } from '../../services/collections-storage.service';
import { DocumentsStorageService } from '../../services/documents-storage.service';
import { AddToCollectionDialogComponent, AddToCollectionDialogData } from './add-to-collection-dialog.component';

const collection: GetCollectionRequest = {
    collection_id: 3,
    collection_name: 'Specs',
    description: null,
    user_id: '1',
    status: CollectionStatus.COMPLETED,
    document_count: 0,
    rag_configurations: [],
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
};

const data: AddToCollectionDialogData = { items: [{ id: 5, name: 'report.pdf', type: 'file' }] };

describe('AddToCollectionDialogComponent', () => {
    let fixture: ComponentFixture<AddToCollectionDialogComponent>;
    /** The template-facing API is `protected` (§18); tests drive it the way the template does. */
    let component: { selectCollection(value: unknown): void; onSubmit(): void; onClose(): void };
    let dialogRef: { close: ReturnType<typeof vi.fn>; disableClose: boolean | undefined };
    let pendingImport: Subject<ImportFromStorageResponse | null>;
    let documentsStorage: { importFromStorage: ReturnType<typeof vi.fn> };

    beforeEach(() => {
        // jsdom has no ResizeObserver; the shared select/tooltip components need one.
        vi.stubGlobal(
            'ResizeObserver',
            class {
                observe(): void {}
                unobserve(): void {}
                disconnect(): void {}
            }
        );
        dialogRef = { close: vi.fn(), disableClose: undefined };
        pendingImport = new Subject();
        documentsStorage = { importFromStorage: vi.fn(() => pendingImport) };

        TestBed.configureTestingModule({
            imports: [AddToCollectionDialogComponent],
            providers: [
                { provide: DIALOG_DATA, useValue: data },
                { provide: DialogRef, useValue: dialogRef },
                { provide: DocumentsStorageService, useValue: documentsStorage },
                {
                    provide: CollectionsStorageService,
                    useValue: {
                        collections: signal([collection]),
                        isCollectionsLoaded: signal(true),
                        getCollections: vi.fn(() => of([collection])),
                    },
                },
            ],
        });
        fixture = TestBed.createComponent(AddToCollectionDialogComponent);
        component = fixture.componentInstance as unknown as typeof component;
        fixture.detectChanges();
    });

    afterEach(() => vi.unstubAllGlobals());

    function buttons(): HTMLButtonElement[] {
        return Array.from((fixture.nativeElement as HTMLElement).querySelectorAll('button'));
    }

    function buttonByText(text: string): HTMLButtonElement | undefined {
        return buttons().find((button) => button.textContent?.trim() === text);
    }

    function submit(): void {
        component.selectCollection(3);
        component.onSubmit();
        fixture.detectChanges();
    }

    it('imports the dialog items into the selected collection', () => {
        submit();

        expect(documentsStorage.importFromStorage).toHaveBeenCalledWith(3, data.items);
    });

    it('does not submit before a collection is selected', () => {
        component.onSubmit();

        expect(documentsStorage.importFromStorage).not.toHaveBeenCalled();
    });

    it('blocks closing and disables Cancel and the close button while submitting', () => {
        submit();

        expect(dialogRef.disableClose).toBe(true);
        expect(buttonByText('Cancel')?.disabled).toBe(true);
        expect(buttons().find((button) => button.getAttribute('aria-label') === 'Close')?.disabled).toBe(true);
        component.onClose();
        expect(dialogRef.close).not.toHaveBeenCalled();
    });

    it('stays open and re-enables closing when the import failed (null result)', () => {
        submit();
        pendingImport.next(null);
        pendingImport.complete();
        fixture.detectChanges();

        expect(dialogRef.close).not.toHaveBeenCalled();
        expect(dialogRef.disableClose).toBe(false);
        expect(buttonByText('Cancel')?.disabled).toBe(false);
    });

    it('closes with the response when the import succeeded', () => {
        const response: ImportFromStorageResponse = { message: 'ok', documents: [], skipped: [] };
        submit();
        pendingImport.next(response);
        pendingImport.complete();

        expect(dialogRef.close).toHaveBeenCalledWith(response);
    });
});
