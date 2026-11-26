import { Component, signal, WritableSignal } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { ActionCode, ResourceCode } from '@shared/models';

import { PermissionsService } from '../../../../services/auth/permissions.service';
import { StorageItem } from '../../../files/models/storage.models';
import { StorageDragService } from '../../../files/services/storage-drag.service';
import { CollectionDropTargetDirective } from '../../directives/collection-drop-target.directive';
import { CollectionCreationService } from '../../services/collection-creation.service';
import { DocumentsStorageService } from '../../services/documents-storage.service';
import { NewCollectionDropZoneComponent } from './new-collection-drop-zone.component';

@Component({
    imports: [NewCollectionDropZoneComponent, CollectionDropTargetDirective],
    template: `
        <app-new-collection-drop-zone>
            <div class="blank">
                <span class="blank-text">blank</span>
                <div
                    class="card"
                    [appCollectionDropTarget]="3"
                >
                    <span class="card-text">card</span>
                </div>
            </div>
        </app-new-collection-drop-zone>
    `,
})
class HostComponent {}

interface DataTransferStub {
    types: string[];
    files: FileList;
    dropEffect: string;
}

const report: StorageItem = { id: 5, name: 'report.pdf', path: 'report.pdf', type: 'file', size: 10 };
const folder: StorageItem = { id: 6, name: 'raw', path: 'raw/', type: 'folder' };
const computerFiles = [new File(['a'], 'notes.md')] as unknown as FileList;

describe('NewCollectionDropZoneComponent', () => {
    let fixture: ComponentFixture<HostComponent>;
    let storageDrag: StorageDragService;
    let granted: Set<string>;
    let isCreating: WritableSignal<boolean>;
    let creation: {
        isCreating: typeof isCreating;
        createCollectionFromStorage: ReturnType<typeof vi.fn>;
        createCollectionFromFiles: ReturnType<typeof vi.fn>;
    };
    let documentsStorage: { isImporting: () => boolean; importFromStorage: ReturnType<typeof vi.fn> };

    function query(selector: string): HTMLElement {
        return (fixture.nativeElement as HTMLElement).querySelector(selector) as HTMLElement;
    }

    function zone(): HTMLElement {
        return query('.new-collection-drop-zone');
    }

    function card(): HTMLElement {
        return query('.card');
    }

    /** A drag event carrying `types`; `['Files']` is a drag of files from the computer. */
    function dispatch(
        type: string,
        element: HTMLElement,
        init: { types?: string[]; relatedTarget?: EventTarget | null } = {}
    ): Event & { dataTransfer: DataTransferStub } {
        const types = init.types ?? (storageDrag.isDragging() ? ['text/plain'] : ['Files']);
        const event = Object.assign(new Event(type, { bubbles: true, cancelable: true }), {
            relatedTarget: init.relatedTarget ?? null,
            dataTransfer: { types, files: computerFiles, dropEffect: 'none' },
        });
        element.dispatchEvent(event);
        fixture.detectChanges();
        return event;
    }

    function startStorageDrag(): void {
        storageDrag.start(report, [report, folder]);
        fixture.detectChanges();
    }

    beforeEach(() => {
        granted = new Set([
            `${ResourceCode.KnowledgeSources}:${ActionCode.Create}`,
            `${ResourceCode.KnowledgeSources}:${ActionCode.Update}`,
            `${ResourceCode.KnowledgeSources}:${ActionCode.Read}`,
            `${ResourceCode.Files}:${ActionCode.Read}`,
        ]);
        isCreating = signal(false);
        creation = {
            isCreating,
            createCollectionFromStorage: vi.fn(),
            createCollectionFromFiles: vi.fn(),
        };
        documentsStorage = { isImporting: () => false, importFromStorage: vi.fn() };

        TestBed.configureTestingModule({
            imports: [HostComponent],
            providers: [
                {
                    provide: PermissionsService,
                    useValue: {
                        can: (resource: ResourceCode, action: ActionCode) => granted.has(`${resource}:${action}`),
                    },
                },
                { provide: CollectionCreationService, useValue: creation },
                { provide: DocumentsStorageService, useValue: documentsStorage },
            ],
        });
        storageDrag = TestBed.inject(StorageDragService);
        fixture = TestBed.createComponent(HostComponent);
        fixture.detectChanges();
    });

    afterEach(() => storageDrag.end());

    it('leaves drags that carry no files alone', () => {
        const dragOver = dispatch('dragover', query('.blank'), { types: ['text/plain'] });
        const drop = dispatch('drop', query('.blank'), { types: ['text/plain'] });

        expect(dragOver.defaultPrevented).toBe(false);
        expect(drop.defaultPrevented).toBe(false);
        expect(zone().classList).not.toContain('new-collection-drop-zone--hovered');
    });

    it('arms while a storage drag is live and disarms when it ends', () => {
        startStorageDrag();
        expect(zone().classList).toContain('new-collection-drop-zone--armed');

        storageDrag.end();
        fixture.detectChanges();

        expect(zone().classList).not.toContain('new-collection-drop-zone--armed');
    });

    it('accepts a storage drag over its blank space and shows the hint', () => {
        startStorageDrag();

        const dragOver = dispatch('dragover', query('.blank-text'));

        expect(dragOver.defaultPrevented).toBe(true);
        expect(dragOver.dataTransfer.dropEffect).toBe('copy');
        expect(zone().classList).toContain('new-collection-drop-zone--hovered');
        expect(query('.new-collection-drop-zone__hint')?.textContent).toContain('Drop to create a new collection');
    });

    it('also accepts dragenter, for browsers that require it before a drop', () => {
        startStorageDrag();

        expect(dispatch('dragenter', query('.blank')).defaultPrevented).toBe(true);
    });

    it('creates a collection from the whole storage drag set on drop, without ending the drag', () => {
        startStorageDrag();
        dispatch('dragover', query('.blank'));

        const drop = dispatch('drop', query('.blank'));

        expect(drop.defaultPrevented).toBe(true);
        expect(creation.createCollectionFromStorage).toHaveBeenCalledWith([report, folder]);
        expect(zone().classList).not.toContain('new-collection-drop-zone--hovered');
        // The source's `dragend` ends it.
        expect(storageDrag.isDragging()).toBe(true);
    });

    it('accepts files from the computer and creates a collection from them on drop', () => {
        expect(zone().classList).not.toContain('new-collection-drop-zone--armed');

        const dragOver = dispatch('dragover', query('.blank'));
        expect(dragOver.defaultPrevented).toBe(true);
        expect(zone().classList).toContain('new-collection-drop-zone--hovered');

        dispatch('drop', query('.blank'));

        expect(creation.createCollectionFromFiles).toHaveBeenCalledWith(computerFiles);
        expect(creation.createCollectionFromStorage).not.toHaveBeenCalled();
    });

    it('leaves a storage drag over a collection to that collection, even though the card stops it', () => {
        startStorageDrag();
        dispatch('dragover', query('.blank'));

        const dragOver = dispatch('dragover', query('.card-text'));

        expect(dragOver.defaultPrevented).toBe(true);
        expect(card().classList).toContain('collection-drop-target--hovered');
        expect(zone().classList).not.toContain('new-collection-drop-zone--hovered');

        dispatch('drop', query('.card-text'));

        expect(documentsStorage.importFromStorage).toHaveBeenCalledWith(3, [report, folder]);
        expect(creation.createCollectionFromStorage).not.toHaveBeenCalled();
    });

    it('refuses files from the computer over a collection card, so the browser does not open them', () => {
        const dragOver = dispatch('dragover', query('.card-text'));

        expect(dragOver.defaultPrevented).toBe(true);
        expect(dragOver.dataTransfer.dropEffect).toBe('none');
        expect(zone().classList).not.toContain('new-collection-drop-zone--hovered');

        dispatch('drop', query('.card-text'));
        expect(creation.createCollectionFromFiles).not.toHaveBeenCalled();
    });

    it('keeps the highlight while moving inside and drops it on leaving the zone', () => {
        dispatch('dragover', query('.blank'));
        const host = query('app-new-collection-drop-zone');

        dispatch('dragleave', host, { relatedTarget: query('.blank-text') });
        expect(zone().classList).toContain('new-collection-drop-zone--hovered');

        dispatch('dragleave', host, { relatedTarget: document.body });
        expect(zone().classList).not.toContain('new-collection-drop-zone--hovered');
    });

    it('refuses drops while a collection is being created', () => {
        isCreating.set(true);
        fixture.detectChanges();
        expect(zone().classList).toContain('new-collection-drop-zone--busy');

        const dragOver = dispatch('dragover', query('.blank'));
        dispatch('drop', query('.blank'));

        expect(dragOver.dataTransfer.dropEffect).toBe('none');
        expect(zone().classList).not.toContain('new-collection-drop-zone--hovered');
        expect(creation.createCollectionFromFiles).not.toHaveBeenCalled();
    });

    it.each([
        [ResourceCode.KnowledgeSources, ActionCode.Create],
        [ResourceCode.KnowledgeSources, ActionCode.Update],
    ])('refuses every drop without %s %s', (resource, action) => {
        granted.delete(`${resource}:${action}`);

        const dragOver = dispatch('dragover', query('.blank'));
        dispatch('drop', query('.blank'));
        startStorageDrag();
        dispatch('drop', query('.blank'));

        expect(dragOver.defaultPrevented).toBe(true);
        expect(dragOver.dataTransfer.dropEffect).toBe('none');
        expect(zone().classList).not.toContain('new-collection-drop-zone--armed');
        expect(creation.createCollectionFromFiles).not.toHaveBeenCalled();
        expect(creation.createCollectionFromStorage).not.toHaveBeenCalled();
    });

    it.each([
        [ResourceCode.KnowledgeSources, ActionCode.Read],
        [ResourceCode.Files, ActionCode.Read],
    ])('refuses storage items, but not computer files, without %s %s', (resource, action) => {
        granted.delete(`${resource}:${action}`);

        dispatch('drop', query('.blank'));
        startStorageDrag();
        dispatch('drop', query('.blank'));

        expect(creation.createCollectionFromFiles).toHaveBeenCalledTimes(1);
        expect(creation.createCollectionFromStorage).not.toHaveBeenCalled();
    });

    it('does not carry a stale highlight into the next drag', () => {
        startStorageDrag();
        dispatch('dragover', query('.blank'));
        storageDrag.end();
        fixture.detectChanges();

        startStorageDrag();

        expect(zone().classList).not.toContain('new-collection-drop-zone--hovered');
    });
});
