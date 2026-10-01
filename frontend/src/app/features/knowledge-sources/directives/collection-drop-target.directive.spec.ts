// Side-effect import: DocumentsStorageService's dependency graph reaches shared/utils/http-error.util.ts,
// which reads the `validationErrors` augmentation declared by this interceptor module.
import '../../../core/interceptors/validation-errors.interceptor';

import { Component, signal } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { ActionCode, ResourceCode } from '@shared/models';
import { Subject } from 'rxjs';

import { PermissionsService } from '../../../services/auth/permissions.service';
import { ToastService } from '../../../services/notifications';
import { StorageItem } from '../../files/models/storage.models';
import { StorageDragService } from '../../files/services/storage-drag.service';
import { ImportFromStorageResponse } from '../models/document.model';
import { CollectionsApiService } from '../services/collections-api.service';
import { CollectionsStorageService } from '../services/collections-storage.service';
import { DocumentsApiService } from '../services/documents-api.service';
import { CollectionDropTargetDirective } from './collection-drop-target.directive';

@Component({
    imports: [CollectionDropTargetDirective],
    template: `
        <div
            class="outer"
            (dragover)="outerDragOvers = outerDragOvers + 1"
            (drop)="outerDrops = outerDrops + 1"
        >
            <div
                class="target"
                [appCollectionDropTarget]="collectionId()"
            >
                <span class="child">child</span>
            </div>
        </div>
    `,
})
class HostComponent {
    readonly collectionId = signal<number | null | undefined>(3);
    outerDragOvers = 0;
    outerDrops = 0;
}

const report: StorageItem = { id: 5, name: 'report.pdf', path: 'report.pdf', type: 'file', size: 10 };
const folder: StorageItem = { id: 6, name: 'raw', path: 'raw/', type: 'folder' };

describe('CollectionDropTargetDirective', () => {
    let fixture: ComponentFixture<HostComponent>;
    let storageDrag: StorageDragService;
    let granted: Set<string>;
    let pendingImport: Subject<ImportFromStorageResponse>;
    let documentsApi: { importFromStorage: ReturnType<typeof vi.fn> };

    function target(): HTMLElement {
        return (fixture.nativeElement as HTMLElement).querySelector('.target') as HTMLElement;
    }

    function dragEvent(type: string, init: { relatedTarget?: EventTarget | null } = {}): Event {
        const event = new Event(type, { bubbles: true, cancelable: true });
        return Object.assign(event, { relatedTarget: init.relatedTarget ?? null });
    }

    function dispatch(type: string, element: HTMLElement = target(), init = {}): Event {
        const event = dragEvent(type, init);
        element.dispatchEvent(event);
        fixture.detectChanges();
        return event;
    }

    function startDrag(): void {
        storageDrag.start(report, [report, folder]);
        fixture.detectChanges();
    }

    beforeEach(() => {
        granted = new Set([
            `${ResourceCode.KnowledgeSources}:${ActionCode.Create}`,
            `${ResourceCode.KnowledgeSources}:${ActionCode.Read}`,
            `${ResourceCode.Files}:${ActionCode.Read}`,
        ]);
        pendingImport = new Subject();
        documentsApi = { importFromStorage: vi.fn(() => pendingImport) };

        TestBed.configureTestingModule({
            imports: [HostComponent],
            providers: [
                {
                    provide: PermissionsService,
                    useValue: {
                        can: (resource: ResourceCode, action: ActionCode) => granted.has(`${resource}:${action}`),
                    },
                },
                { provide: CollectionsStorageService, useValue: {} },
                { provide: CollectionsApiService, useValue: {} },
                { provide: DocumentsApiService, useValue: documentsApi },
                { provide: ToastService, useValue: { success: vi.fn(), warning: vi.fn(), error: vi.fn() } },
            ],
        });
        storageDrag = TestBed.inject(StorageDragService);
        fixture = TestBed.createComponent(HostComponent);
        fixture.detectChanges();
    });

    afterEach(() => storageDrag.end());

    it('is inert and lets drags pass through while no storage drag is live (e.g. OS files)', () => {
        const dragOver = dispatch('dragover');
        const drop = dispatch('drop');

        expect(target().classList).not.toContain('collection-drop-target--armed');
        expect(dragOver.defaultPrevented).toBe(false);
        expect(drop.defaultPrevented).toBe(false);
        expect(fixture.componentInstance.outerDragOvers).toBe(1);
        expect(fixture.componentInstance.outerDrops).toBe(1);
        expect(documentsApi.importFromStorage).not.toHaveBeenCalled();
    });

    it('arms while a storage drag is live and disarms when it ends', () => {
        startDrag();
        expect(target().classList).toContain('collection-drop-target--armed');

        storageDrag.end();
        fixture.detectChanges();

        expect(target().classList).not.toContain('collection-drop-target--armed');
    });

    it('claims the drag over it: accepts it as a copy, highlights, and stops it reaching ancestors', () => {
        startDrag();

        const dragOver = dispatch('dragover');

        expect(dragOver.defaultPrevented).toBe(true);
        expect(target().classList).toContain('collection-drop-target--hovered');
        expect(fixture.componentInstance.outerDragOvers).toBe(0);
    });

    it('also accepts dragenter, for browsers that require it before a drop', () => {
        startDrag();

        expect(dispatch('dragenter').defaultPrevented).toBe(true);
    });

    it('keeps the highlight while moving onto a child and drops it on leaving the host', () => {
        startDrag();
        dispatch('dragover');
        const child = target().querySelector('.child') as HTMLElement;

        dispatch('dragleave', target(), { relatedTarget: child });
        expect(target().classList).toContain('collection-drop-target--hovered');

        dispatch('dragleave', target(), { relatedTarget: document.body });
        expect(target().classList).not.toContain('collection-drop-target--hovered');
    });

    it('imports the whole drag set into the bound collection on drop, without ending the drag', () => {
        startDrag();

        const drop = dispatch('drop');

        expect(drop.defaultPrevented).toBe(true);
        expect(fixture.componentInstance.outerDrops).toBe(0);
        expect(documentsApi.importFromStorage).toHaveBeenCalledWith(3, [5, 6]);
        expect(target().classList).not.toContain('collection-drop-target--hovered');
        // The source's `dragend` ends it; ending here would unmount a kept-alive source first.
        expect(storageDrag.isDragging()).toBe(true);
    });

    it('refuses drops while an import into the same collection is in flight', () => {
        startDrag();
        dispatch('drop');
        expect(target().classList).toContain('collection-drop-target--busy');

        const dragOver = dispatch('dragover');
        dispatch('drop');

        expect(dragOver.defaultPrevented).toBe(true);
        expect(target().classList).not.toContain('collection-drop-target--hovered');
        expect(documentsApi.importFromStorage).toHaveBeenCalledTimes(1);

        pendingImport.error(new Error('boom'));
        fixture.detectChanges();
        expect(target().classList).not.toContain('collection-drop-target--busy');
    });

    it.each([null, undefined])('stays inert without a collection (%s)', (collectionId) => {
        fixture.componentInstance.collectionId.set(collectionId);
        startDrag();

        expect(target().classList).not.toContain('collection-drop-target--armed');
        expect(dispatch('dragover').defaultPrevented).toBe(false);
    });

    it.each([
        [ResourceCode.KnowledgeSources, ActionCode.Create],
        [ResourceCode.KnowledgeSources, ActionCode.Read],
        [ResourceCode.Files, ActionCode.Read],
    ])('stays inert without %s %s', (resource, action) => {
        granted.delete(`${resource}:${action}`);
        startDrag();

        expect(target().classList).not.toContain('collection-drop-target--armed');
        dispatch('drop');
        expect(documentsApi.importFromStorage).not.toHaveBeenCalled();
    });

    it('does not carry a stale highlight into the next drag', () => {
        startDrag();
        dispatch('dragover');
        storageDrag.end();
        fixture.detectChanges();

        startDrag();

        expect(target().classList).not.toContain('collection-drop-target--hovered');
    });
});
