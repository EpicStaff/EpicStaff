import { computed, inject, Injectable, signal } from '@angular/core';
import { IPoint, PointExtensions } from '@foblex/2d';
import { FFlowComponent } from '@foblex/flow';
import { ActionCode, NodeType, ResourceCode } from '@shared/models';

import { PermissionsService } from '../../services/auth/permissions.service';
import { GraphNoteModel, NoteLinkedRegion } from '../core/models/node.model';
import { FlowService } from '../services/flow.service';
import { NodeFactoryService } from '../services/node-factory.service';
import { UndoRedoService } from '../services/undo-redo.service';
import { FlowArrangeAnimatorService } from './flow-arrange-animator.service';
import { FlowSelectionManagerService } from './flow-selection-manager.service';

export interface NoteDrawState {
    active: boolean;
    startFlowPoint: IPoint | null;
    currentFlowPoint: IPoint | null;
    /** When set, draw completion updates this note's region instead of creating a new note. */
    existingNoteId?: string;
}

const MIN_REGION_PX = 20;
const NOTE_WIDTH = 200;
const NOTE_HEIGHT = 150;
const PLACEMENT_OFFSET = 8;

/**
 * Manages note-specific interactions on the flow canvas:
 * area-draw gestures, linked-region highlight, region resize,
 * and note node placement.
 *
 * Provided at the FlowGraphComponent level — one instance per editor.
 */
@Injectable()
export class NoteInteractionService {
    private readonly flowService = inject(FlowService);
    private readonly selectionManager = inject(FlowSelectionManagerService);
    private readonly nodeFactory = inject(NodeFactoryService);
    private readonly permissionService = inject(PermissionsService);
    private readonly arrangeAnimator = inject(FlowArrangeAnimatorService);
    private readonly undoRedoService = inject(UndoRedoService);

    // ── Draw state ──────────────────────────────────────────────────

    readonly noteDrawState = signal<NoteDrawState | null>(null);

    readonly noteDrawRect = computed(() => {
        const state = this.noteDrawState();
        if (!state?.active || !state.startFlowPoint || !state.currentFlowPoint) return null;
        const x = Math.min(state.startFlowPoint.x, state.currentFlowPoint.x);
        const y = Math.min(state.startFlowPoint.y, state.currentFlowPoint.y);
        const width = Math.abs(state.currentFlowPoint.x - state.startFlowPoint.x);
        const height = Math.abs(state.currentFlowPoint.y - state.startFlowPoint.y);
        return { x, y, width, height };
    });

    /** Set after a draw gesture completes — the click event that follows the pointerup must not clear the selection. */
    suppressNextClick = false;

    readonly isDrawActive = computed(() => !!this.noteDrawState()?.active);

    // ── Linked-region highlight ─────────────────────────────────────

    readonly activeNoteLinkedRegion = computed(() => {
        const selectedIds = this.selectionManager.selectedNodeIds();
        const hoveredId = this.hoveredNodeId();

        const selectedNoteId = selectedIds.length === 1 ? selectedIds[0] : null;
        if (selectedNoteId) {
            const selectedNode = this.flowService.nodes().find((n) => n.id === selectedNoteId);
            if (selectedNode?.type === NodeType.NOTE) {
                const noteNode = selectedNode as GraphNoteModel;
                if (noteNode.data.linkedRegion) {
                    return { ...noteNode.data.linkedRegion, color: noteNode.data.backgroundColor };
                }
            }
        }

        if (hoveredId && hoveredId !== selectedNoteId) {
            const node = this.flowService.nodes().find((n) => n.id === hoveredId);
            if (node?.type === NodeType.NOTE) {
                const noteNode = node as GraphNoteModel;
                if (noteNode.data.linkedRegion) {
                    return { ...noteNode.data.linkedRegion, color: noteNode.data.backgroundColor };
                }
            }
        }

        return null;
    });

    readonly isNoteRegionResizable = computed(() => {
        if (!this.permissionService.can(ResourceCode.Flows, ActionCode.Update)) return false;

        const selectedIds = this.selectionManager.selectedNodeIds();
        if (selectedIds.length !== 1) return false;
        const node = this.flowService.nodes().find((n) => n.id === selectedIds[0]);
        return !!node && node.type === NodeType.NOTE && !!(node as GraphNoteModel).data.linkedRegion;
    });

    /** Injected by the component — the computed needs a hovered-node signal it does not own. */
    hoveredNodeId: () => string | null = () => null;

    // ── Region resize ───────────────────────────────────────────────

    readonly regionResizeActive = signal(false);
    private regionResizeState: {
        direction: string;
        noteId: string;
        originalRegion: NoteLinkedRegion;
        startClientPoint: IPoint;
    } | null = null;

    onRegionResizeStart(event: PointerEvent, direction: string, fFlowComponent: FFlowComponent): void {
        if (!this.isNoteRegionResizable()) return;
        event.stopPropagation();
        event.preventDefault();
        const selectedIds = this.selectionManager.selectedNodeIds();
        if (selectedIds.length !== 1) return;
        const node = this.flowService.nodes().find((n) => n.id === selectedIds[0]) as GraphNoteModel | undefined;
        if (!node?.data.linkedRegion) return;

        this.regionResizeState = {
            direction,
            noteId: node.id,
            originalRegion: { ...node.data.linkedRegion },
            startClientPoint: { x: event.clientX, y: event.clientY },
        };
        this.regionResizeActive.set(true);

        const moveHandler = (moveEvent: PointerEvent): void => this.onRegionResizeMove(moveEvent, fFlowComponent);
        const upHandler = (): void => {
            this.onRegionResizeEnd();
            document.removeEventListener('pointermove', moveHandler);
            document.removeEventListener('pointerup', upHandler);
        };
        document.addEventListener('pointermove', moveHandler);
        document.addEventListener('pointerup', upHandler);
    }

    private onRegionResizeMove(event: PointerEvent, fFlowComponent: FFlowComponent): void {
        if (!this.regionResizeState) return;
        const { direction, noteId, originalRegion, startClientPoint } = this.regionResizeState;

        const startFlow = fFlowComponent.getPositionInFlow(
            PointExtensions.initialize(startClientPoint.x, startClientPoint.y)
        );
        const currentFlow = fFlowComponent.getPositionInFlow(PointExtensions.initialize(event.clientX, event.clientY));
        const dx = currentFlow.x - startFlow.x;
        const dy = currentFlow.y - startFlow.y;

        let { x, y, width, height } = originalRegion;

        if (direction === 'move') {
            x += dx;
            y += dy;
        } else {
            if (direction.includes('n')) {
                y += dy;
                height -= dy;
            }
            if (direction.includes('s')) {
                height += dy;
            }
            if (direction.includes('w')) {
                x += dx;
                width -= dx;
            }
            if (direction.includes('e')) {
                width += dx;
            }

            const MIN_REGION = 20;
            if (width < MIN_REGION) {
                width = MIN_REGION;
                if (direction.includes('w')) x = originalRegion.x + originalRegion.width - MIN_REGION;
            }
            if (height < MIN_REGION) {
                height = MIN_REGION;
                if (direction.includes('n')) y = originalRegion.y + originalRegion.height - MIN_REGION;
            }
        }

        const node = this.flowService.nodes().find((n) => n.id === noteId) as GraphNoteModel | undefined;
        if (!node) return;

        const updatedNode: GraphNoteModel = {
            ...node,
            data: { ...node.data, linkedRegion: { x, y, width, height } },
        };
        this.flowService.updateNode(updatedNode);
    }

    private onRegionResizeEnd(): void {
        this.regionResizeState = null;
        this.regionResizeActive.set(false);
    }

    // ── Draw gesture pointer handlers ───────────────────────────────

    startAreaDraw(existingNoteId?: string): void {
        this.noteDrawState.set({
            active: true,
            startFlowPoint: null,
            currentFlowPoint: null,
            existingNoteId,
        });
    }

    cancelDraw(): void {
        this.noteDrawState.set(null);
    }

    /** Handles pointerdown during an active draw. Returns true if consumed. */
    handlePointerDown(event: PointerEvent, fFlowComponent: FFlowComponent): boolean {
        const currentDraw = this.noteDrawState();
        if (!currentDraw?.active) return false;

        const flowPoint = fFlowComponent.getPositionInFlow(PointExtensions.initialize(event.clientX, event.clientY));
        this.noteDrawState.set({
            active: true,
            startFlowPoint: flowPoint,
            currentFlowPoint: flowPoint,
            existingNoteId: currentDraw.existingNoteId,
        });
        return true;
    }

    /** Handles pointermove during an active draw. Returns true if consumed. */
    handlePointerMove(event: PointerEvent, fFlowComponent: FFlowComponent): boolean {
        if (!this.noteDrawState()?.active) return false;

        const flowPoint = fFlowComponent.getPositionInFlow(PointExtensions.initialize(event.clientX, event.clientY));
        this.noteDrawState.update((state) => (state ? { ...state, currentFlowPoint: flowPoint } : state));
        return true;
    }

    /**
     * Handles pointerup during an active draw. Returns the created note node
     * when a new note was placed, or null (for reselect-area or cancelled draws).
     */
    handlePointerUp(
        event: PointerEvent,
        fFlowComponent: FFlowComponent,
        snapToGrid: (value: number) => number
    ): GraphNoteModel | null {
        const drawState = this.noteDrawState();
        if (!drawState?.active) return null;

        const endFlowPoint = fFlowComponent.getPositionInFlow(PointExtensions.initialize(event.clientX, event.clientY));
        const start = drawState.startFlowPoint;
        this.noteDrawState.set(null);
        this.suppressNextClick = true;

        if (!start) return null;

        const width = Math.abs(endFlowPoint.x - start.x);
        const height = Math.abs(endFlowPoint.y - start.y);
        const hasRegion = width >= MIN_REGION_PX && height >= MIN_REGION_PX;

        const linkedRegion = hasRegion
            ? {
                  x: Math.min(start.x, endFlowPoint.x),
                  y: Math.min(start.y, endFlowPoint.y),
                  width,
                  height,
              }
            : undefined;

        // Reselect area mode: update the existing note's region instead of creating a new one.
        if (drawState.existingNoteId) {
            this.applyReselectArea(drawState.existingNoteId, linkedRegion, fFlowComponent);
            return null;
        }

        // Place the note node near the cursor end point, just outside the region.
        let placeX = endFlowPoint.x;
        let placeY = endFlowPoint.y;
        if (hasRegion) {
            const draggedLeft = endFlowPoint.x <= start.x;
            const draggedUp = endFlowPoint.y <= start.y;
            placeX = draggedLeft ? endFlowPoint.x - NOTE_WIDTH - PLACEMENT_OFFSET : endFlowPoint.x + PLACEMENT_OFFSET;
            placeY = draggedUp ? endFlowPoint.y - NOTE_HEIGHT - PLACEMENT_OFFSET : endFlowPoint.y + PLACEMENT_OFFSET;
        }

        return this.createNoteWithRegion(PointExtensions.initialize(placeX, placeY), linkedRegion, snapToGrid);
    }

    // ── Note creation ───────────────────────────────────────────────

    /** Merges user-derived default colour into note creation overrides. */
    buildNoteCreationOverrides(overrides: Partial<GraphNoteModel>): Partial<GraphNoteModel> {
        return {
            ...overrides,
            data: {
                content: 'Add your note here...',
                ...(overrides.data ?? {}),
            },
        };
    }

    // ── Private ─────────────────────────────────────────────────────

    private applyReselectArea(
        existingNoteId: string,
        linkedRegion: NoteLinkedRegion | undefined,
        fFlowComponent: FFlowComponent
    ): void {
        const existingNode = this.flowService.nodes().find((n) => n.id === existingNoteId) as
            | GraphNoteModel
            | undefined;
        if (!existingNode) return;

        const updatedNode: GraphNoteModel = {
            ...existingNode,
            data: {
                ...existingNode.data,
                linkedRegion: linkedRegion ?? existingNode.data.linkedRegion,
            },
        };
        this.flowService.updateNode(updatedNode);
        this.selectionManager.selectedNodeIds.set([existingNode.id]);
        fFlowComponent.select([existingNode.id], []);
    }

    private createNoteWithRegion(
        flowPosition: IPoint,
        linkedRegion: NoteLinkedRegion | undefined,
        snapToGrid: (value: number) => number
    ): GraphNoteModel {
        this.arrangeAnimator.markUnarranged();
        this.undoRedoService.stateChanged();

        const position = { x: snapToGrid(flowPosition.x), y: snapToGrid(flowPosition.y) };
        const newNode = this.nodeFactory.createNode(NodeType.NOTE, { position }) as GraphNoteModel;
        const withData: GraphNoteModel = {
            ...newNode,
            position,
            data: { ...newNode.data, linkedRegion },
        };
        this.flowService.addNode(withData);
        return withData;
    }
}
