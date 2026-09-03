import { computed, Injectable, signal } from '@angular/core';

export interface DraggedSharedSurface {
    id: number;
    name: string;
}

/**
 * Tracks the shared surface currently being native-dragged from the
 * Shared Surfaces tree, so agents can act as drop targets.
 */
@Injectable({ providedIn: 'root' })
export class SurfaceDragService {
    private readonly draggedSignal = signal<DraggedSharedSurface | null>(null);

    readonly dragged = this.draggedSignal.asReadonly();
    readonly isDragging = computed(() => this.draggedSignal() != null);

    start(surface: DraggedSharedSurface): void {
        this.draggedSignal.set(surface);
    }

    end(): void {
        this.draggedSignal.set(null);
    }
}
