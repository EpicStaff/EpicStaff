import { DOCUMENT } from '@angular/common';
import { computed, inject, Injectable, signal } from '@angular/core';

import { StorageItem } from '../models/storage.models';

const LISTENER_OPTIONS: AddEventListenerOptions = { capture: true };

/**
 * Tracks the storage items currently being native-dragged from a storage tree,
 * so unrelated features (e.g. surface cards, knowledge collections) can act as drop targets.
 *
 * `dragged` is the row the user grabbed; `draggedItems` is the whole drag set
 * (the grabbed row plus the rest of the selection when it was part of it).
 *
 * Safety net: if the dragged row is removed from the DOM mid-drag, some browsers (Firefox)
 * never fire `dragend`. Native DnD suppresses mouse/pointer events while a drag is live, so
 * once the drag has been seen over the page (`dragover`), the first `mousedown`, or a primary
 * `pointermove` with no button held, means it is over and the state is cleared.
 */
@Injectable({ providedIn: 'root' })
export class StorageDragService {
    private readonly draggedSignal = signal<StorageItem | null>(null);
    private readonly draggedItemsSignal = signal<StorageItem[]>([]);

    readonly dragged = this.draggedSignal.asReadonly();
    readonly draggedItems = this.draggedItemsSignal.asReadonly();
    readonly isDragging = computed(() => this.draggedSignal() != null);

    private readonly document = inject(DOCUMENT);
    private readonly armSafetyNet = (): void => {
        this.document.addEventListener('pointermove', this.endFromPointer, LISTENER_OPTIONS);
        this.document.addEventListener('mousedown', this.endFromPointer, LISTENER_OPTIONS);
    };
    /** A mousedown, or a primary pointer moving with no button held, means the drag is over. */
    private readonly endFromPointer = (event: Event): void => {
        const pointer = event as Partial<PointerEvent>;
        const isReleasedPrimaryPointer =
            event.type === 'pointermove' && pointer.isPrimary === true && pointer.buttons === 0;
        if (event.type === 'mousedown' || isReleasedPrimaryPointer) this.end();
    };

    start(item: StorageItem, items: StorageItem[] = [item]): void {
        this.removeSafetyNet();
        this.draggedSignal.set(item);
        this.draggedItemsSignal.set(items.length ? items : [item]);
        this.document.addEventListener('dragover', this.armSafetyNet, { ...LISTENER_OPTIONS, once: true });
    }

    end(): void {
        this.removeSafetyNet();
        this.draggedSignal.set(null);
        this.draggedItemsSignal.set([]);
    }

    private removeSafetyNet(): void {
        this.document.removeEventListener('dragover', this.armSafetyNet, LISTENER_OPTIONS);
        this.document.removeEventListener('pointermove', this.endFromPointer, LISTENER_OPTIONS);
        this.document.removeEventListener('mousedown', this.endFromPointer, LISTENER_OPTIONS);
    }
}
