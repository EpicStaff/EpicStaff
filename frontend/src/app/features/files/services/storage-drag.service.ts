import { computed, Injectable, signal } from '@angular/core';

import { StorageItem } from '../models/storage.models';

/**
 * Tracks the storage item currently being native-dragged from a storage tree,
 * so unrelated features (e.g. surface cards) can act as drop targets.
 */
@Injectable({ providedIn: 'root' })
export class StorageDragService {
    private readonly draggedSignal = signal<StorageItem | null>(null);

    readonly dragged = this.draggedSignal.asReadonly();
    readonly isDragging = computed(() => this.draggedSignal() != null);

    start(item: StorageItem): void {
        this.draggedSignal.set(item);
    }

    end(): void {
        this.draggedSignal.set(null);
    }
}
