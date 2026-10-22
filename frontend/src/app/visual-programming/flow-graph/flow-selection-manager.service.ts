import { computed, inject, Injectable, signal } from '@angular/core';
import { IPoint } from '@foblex/2d';
import { NodeType } from '@shared/models';

import { FlowService } from '../services/flow.service';

/**
 * Manages selection state for the flow graph: which nodes and connections
 * are selected, multi-select mode, and the trigger functions that
 * Foblex uses to decide gesture behavior.
 *
 * Provided at the FlowGraphComponent level — one instance per editor.
 */
@Injectable()
export class FlowSelectionManagerService {
    private readonly flowService = inject(FlowService);

    // ── Selection state ──────────────────────────────────────────────
    readonly selectedNodeIds = signal<string[]>([]);
    readonly selectedConnectionIds = signal<Set<string>>(new Set());
    readonly multiSelectActive = signal<boolean>(false);

    readonly selectedNodeCount = computed(() => {
        const nodes = this.flowService.nodes();
        return this.selectedNodeIds().filter((id) => {
            const type = nodes.find((n) => n.id === id)?.type;
            return type !== NodeType.START && type !== NodeType.END;
        }).length;
    });

    readonly allSelectedAreCdt = computed(() => {
        const ids = this.selectedNodeIds();
        if (ids.length === 0) return false;
        const nodes = this.flowService.nodes();
        return ids.every((id) => nodes.find((n) => n.id === id)?.type === NodeType.CLASSIFICATION_TABLE);
    });

    readonly extractableSelectedNodeIds = computed<Set<string>>(() => {
        const nodes = this.flowService.nodes();
        return new Set(
            this.selectedNodeIds().filter((id) => {
                const type = nodes.find((n) => n.id === id)?.type;
                return type !== NodeType.START && type !== NodeType.END;
            })
        );
    });

    // ── Trigger functions for Foblex ─────────────────────────────────

    readonly multiSelectTrigger = (event: MouseEvent | TouchEvent | WheelEvent): boolean =>
        this.multiSelectActive() || (event instanceof MouseEvent && (event.shiftKey || event.ctrlKey || event.metaKey));

    readonly selectionAreaTrigger = (event: MouseEvent | TouchEvent | WheelEvent): boolean =>
        this.multiSelectActive() || (event instanceof MouseEvent && event.shiftKey);

    readonly canvasMoveTrigger = (event: MouseEvent | TouchEvent | WheelEvent): boolean =>
        !this.multiSelectActive() && !(event instanceof MouseEvent && event.shiftKey);

    // ── Drag coordinate tracking (used by onSelectionChange) ─────────

    private _dragStartClientX: number | null = null;
    private _dragStartClientY: number | null = null;
    private _dragEndClientX: number | null = null;
    private _dragEndClientY: number | null = null;
    private _isReselecting = false;

    recordPointerDown(event: PointerEvent): void {
        this._dragStartClientX = event.clientX;
        this._dragStartClientY = event.clientY;
        this._dragEndClientX = null;
        this._dragEndClientY = null;
    }

    recordPointerUp(event: PointerEvent): void {
        this._dragEndClientX = event.clientX;
        this._dragEndClientY = event.clientY;
    }

    // ── Selection logic ──────────────────────────────────────────────

    /**
     * Processes a Foblex selection-change event.
     *
     * Callers must supply two callbacks so the service can interact with
     * FFlowComponent without depending on it directly:
     *  - `getPositionInFlow`: converts screen coordinates to flow coordinates
     *  - `selectInFlow`: calls `fFlowComponent.select(nodeIds, connectionIds)`
     *  - `getSelectedConnectionIds`: returns the current Foblex connection selection
     */
    handleSelectionChange(
        event: { nodeIds: string[] },
        mouseCursorPosition: IPoint,
        callbacks: {
            getPositionInFlow: (point: IPoint) => IPoint;
            selectInFlow: (nodeIds: string[], connectionIds: string[]) => void;
            getSelectedConnectionIds: () => Set<string>;
        }
    ): void {
        if (this._isReselecting) {
            this._isReselecting = false;
            return;
        }

        const nodeIds = event.nodeIds;

        // In multiselect mode, ignore automatic empty-selection events (e.g. from CDK overlay interactions)
        if (this.multiSelectActive() && nodeIds.length === 0) {
            return;
        }

        const endX = this._dragEndClientX ?? mouseCursorPosition.x;
        const endY = this._dragEndClientY ?? mouseCursorPosition.y;

        const isLeftToRight =
            nodeIds.length > 0 && this._dragStartClientX !== null && endX - this._dragStartClientX > 10;

        if (isLeftToRight) {
            const selStart = callbacks.getPositionInFlow({ x: this._dragStartClientX!, y: this._dragStartClientY! });
            const selEnd = callbacks.getPositionInFlow({ x: endX, y: endY });
            const selLeft = Math.min(selStart.x, selEnd.x);
            const selRight = Math.max(selStart.x, selEnd.x);
            const selTop = Math.min(selStart.y, selEnd.y);
            const selBottom = Math.max(selStart.y, selEnd.y);

            const allNodes = this.flowService.nodes();
            const containedIds = nodeIds.filter((id) => {
                const node = allNodes.find((n) => n.id === id);
                if (!node) return false;
                return (
                    node.position.x >= selLeft &&
                    node.position.x + (node.size?.width ?? 0) <= selRight &&
                    node.position.y >= selTop &&
                    node.position.y + (node.size?.height ?? 0) <= selBottom
                );
            });

            if (containedIds.length !== nodeIds.length) {
                this._isReselecting = true;
                this.selectedNodeIds.set(containedIds);
                callbacks.selectInFlow(containedIds, []);
                return;
            }
        }

        this.selectedNodeIds.set(nodeIds);
        this.selectedConnectionIds.set(callbacks.getSelectedConnectionIds());
    }

    toggleMultiSelect(): void {
        const wasActive = this.multiSelectActive();
        this.multiSelectActive.update((v) => !v);
        if (wasActive) {
            this.clearSelection();
        }
    }

    /**
     * Called on Escape key — exits multi-select mode and clears the selection.
     * Returns true if multi-select was active and was deactivated, false otherwise.
     */
    escapeSelection(): boolean {
        if (this.multiSelectActive()) {
            this.multiSelectActive.set(false);
            this.clearSelection();
            return true;
        }
        return false;
    }

    /**
     * Handles a click on the flow canvas background — exits multi-select if
     * no node was clicked and the user wasn't dragging.
     */
    handleFlowClick(event: MouseEvent, isDragging: boolean): void {
        if (this.multiSelectActive() && !isDragging && !(event.target as Element).closest('app-flow-base-node')) {
            this.multiSelectActive.set(false);
            this.clearSelection();
        }
    }

    /**
     * Clears the node and connection selection. The caller should also call
     * `fFlowComponent.select([], [])` after this to sync the Foblex state.
     */
    clearSelection(): void {
        this.selectedNodeIds.set([]);
        this.selectedConnectionIds.set(new Set());
    }
}
