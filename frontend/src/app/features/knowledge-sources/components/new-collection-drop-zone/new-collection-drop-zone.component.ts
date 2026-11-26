import {
    ChangeDetectionStrategy,
    Component,
    computed,
    DestroyRef,
    effect,
    ElementRef,
    inject,
    signal,
} from '@angular/core';
import { AppSvgIconComponent } from '@shared/components';
import { ActionCode, ResourceCode } from '@shared/models';

import { PermissionsService } from '../../../../services/auth/permissions.service';
import { StorageDragService } from '../../../files/services/storage-drag.service';
import { COLLECTION_DROP_TARGET_SELECTOR } from '../../directives/collection-drop-target.directive';
import { canImportStorageToKnowledge } from '../../helpers/storage-import.util';
import { CollectionCreationService } from '../../services/collection-creation.service';

/** What is being dragged: storage items from the Files tab, or files from the user's computer. */
type DropKind = 'storage' | 'files';

const CAPTURE: AddEventListenerOptions = { capture: true };

/**
 * Wraps the parts of the Knowledge Sources page that are not a collection (the sidebar around its cards, the
 * empty details pane) and turns files dropped there into a new collection: `CollectionCreationService` creates
 * it, fills it with the dropped storage items or files, and opens the Create New Collection wizard.
 *
 * A drag over an existing collection (`appCollectionDropTarget`) is left to that collection — it never creates
 * one. Collection cards take storage items only, so a computer file over a card is refused rather than dropped
 * on the page, where the browser would open it.
 *
 * Its listeners run in the capture phase: the collection cards inside claim storage drags and stop them, and the
 * zone still has to see the pointer arrive over a card to drop its own highlight.
 */
@Component({
    selector: 'app-new-collection-drop-zone',
    templateUrl: './new-collection-drop-zone.component.html',
    styleUrls: ['./new-collection-drop-zone.component.scss'],
    imports: [AppSvgIconComponent],
    changeDetection: ChangeDetectionStrategy.OnPush,
    host: {
        '(dragleave)': 'onDragLeave($event)',
    },
})
export class NewCollectionDropZoneComponent {
    private readonly storageDrag = inject(StorageDragService);
    private readonly permissionsService = inject(PermissionsService);
    private readonly collectionCreation = inject(CollectionCreationService);
    private readonly host = inject<ElementRef<HTMLElement>>(ElementRef).nativeElement;

    private readonly hovered = signal<boolean>(false);
    /** The "Create collection" button's rule: the wizard updates the collection it creates. */
    private readonly canCreate = computed(
        () =>
            this.permissionsService.can(ResourceCode.KnowledgeSources, ActionCode.Create) &&
            this.permissionsService.can(ResourceCode.KnowledgeSources, ActionCode.Update)
    );
    private readonly canCreateFromStorage = computed(
        () => this.canCreate() && canImportStorageToKnowledge(this.permissionsService)
    );

    /** Only a storage drag is known before it reaches the zone; a dragged computer file only shows as hover. */
    protected readonly isArmed = computed(() => this.storageDrag.isDragging() && this.canCreateFromStorage());
    protected readonly isBusy = this.collectionCreation.isCreating;
    protected readonly isHovered = computed(() => this.hovered() && !this.isBusy());

    /** A drag can end (Esc, drop elsewhere) without a `dragleave` here; never carry hover into the next one. */
    private readonly clearHoverWhenStorageDragEnds = effect(() => {
        if (!this.storageDrag.isDragging()) this.hovered.set(false);
    });

    constructor() {
        const onDragOver = (event: Event): void => this.onDragOver(event as DragEvent);
        const onDrop = (event: Event): void => this.onDrop(event as DragEvent);
        this.host.addEventListener('dragenter', onDragOver, CAPTURE);
        this.host.addEventListener('dragover', onDragOver, CAPTURE);
        this.host.addEventListener('drop', onDrop, CAPTURE);
        inject(DestroyRef).onDestroy(() => {
            this.host.removeEventListener('dragenter', onDragOver, CAPTURE);
            this.host.removeEventListener('dragover', onDragOver, CAPTURE);
            this.host.removeEventListener('drop', onDrop, CAPTURE);
        });
    }

    onDragLeave(event: DragEvent): void {
        const related = event.relatedTarget as Node | null;
        if (related && this.host.contains(related)) return;
        this.hovered.set(false);
    }

    private onDragOver(event: DragEvent): void {
        const kind = this.dropKind(event);
        if (!kind) return;
        if (this.isOverCollection(event)) {
            this.hovered.set(false);
            if (kind === 'files') this.refuse(event);
            return;
        }
        if (!this.accepts(kind) || this.isBusy()) {
            this.refuse(event);
            this.hovered.set(false);
            return;
        }
        event.preventDefault();
        if (event.dataTransfer) event.dataTransfer.dropEffect = 'copy';
        this.hovered.set(true);
    }

    private onDrop(event: DragEvent): void {
        const kind = this.dropKind(event);
        if (!kind || this.isOverCollection(event)) return;
        event.preventDefault();
        this.hovered.set(false);
        if (!this.accepts(kind) || this.isBusy()) return;
        if (kind === 'storage') {
            // The drag itself is ended by the source's `dragend`, which fires right after this drop.
            this.collectionCreation.createCollectionFromStorage(this.storageDrag.draggedItems());
            return;
        }
        const files = event.dataTransfer?.files;
        if (files?.length) this.collectionCreation.createCollectionFromFiles(files);
    }

    /** `null` for any other drag (text, links), which the zone leaves alone. */
    private dropKind(event: DragEvent): DropKind | null {
        if (this.storageDrag.isDragging()) return 'storage';
        const types = event.dataTransfer?.types;
        return types && Array.from(types).includes('Files') ? 'files' : null;
    }

    private accepts(kind: DropKind): boolean {
        return kind === 'storage' ? this.canCreateFromStorage() : this.canCreate();
    }

    private isOverCollection(event: DragEvent): boolean {
        const target = event.target as Node | null;
        // Firefox can target a text node.
        const element = target instanceof Element ? target : (target?.parentElement ?? null);
        const collection = element?.closest(COLLECTION_DROP_TARGET_SELECTOR);
        return !!collection && this.host.contains(collection);
    }

    /** Claims the drag only to say no: the cursor shows it, and the browser does not open a dropped file. */
    private refuse(event: DragEvent): void {
        event.preventDefault();
        if (event.dataTransfer) event.dataTransfer.dropEffect = 'none';
    }
}
