import { computed, Injectable, signal } from '@angular/core';

export interface DraggedAgent {
    id: number;
    name: string;
}

/**
 * Tracks the agent currently being native-dragged in the explorer, so group blocks can act as drop
 * targets. Kept apart from SurfaceDragService: a dragged agent must never trigger the
 * "drop a shared surface onto an agent" targets.
 */
@Injectable({ providedIn: 'root' })
export class AgentDragService {
    private readonly draggedSignal = signal<DraggedAgent | null>(null);

    readonly dragged = this.draggedSignal.asReadonly();
    readonly isDragging = computed(() => this.draggedSignal() != null);

    start(agent: DraggedAgent): void {
        this.draggedSignal.set(agent);
    }

    end(): void {
        this.draggedSignal.set(null);
    }
}
