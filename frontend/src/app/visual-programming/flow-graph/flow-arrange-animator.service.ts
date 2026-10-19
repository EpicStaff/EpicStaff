import { inject, Injectable, signal } from '@angular/core';
import { IPoint } from '@foblex/2d';

import { computeLayout } from '../core/layout/compute-layout';
import { NodeModel } from '../core/models/node.model';
import { FlowService } from '../services/flow.service';
import { FlowReadOnlyService } from '../services/flow-readonly.service';
import { UndoRedoService } from '../services/undo-redo.service';
import { FlowRoutingOrchestratorService } from './flow-routing-orchestrator.service';

/**
 * Callbacks the component provides so the animator can interact with
 * the canvas without holding component-level references directly.
 */
export interface ArrangeAnimatorCallbacks {
    detectChanges(): void;
    redraw(): void;
    fitToScreen(padding: IPoint, animate: boolean): void;
}

/**
 * Manages the auto-arrange animation: computes a Sugiyama layout, then
 * animates every node from its current position to the target over 400 ms
 * with ease-in-out quadratic easing.
 *
 * Provided at the FlowGraphComponent level.
 */
@Injectable()
export class FlowArrangeAnimatorService {
    private readonly flowService = inject(FlowService);
    private readonly flowReadOnly = inject(FlowReadOnlyService);
    private readonly undoRedoService = inject(UndoRedoService);
    private readonly routingOrchestrator = inject(FlowRoutingOrchestratorService);

    private arrangeAnimationId: number | null = null;
    private arrangingLock = false;

    readonly hasUnarrangedChanges = signal(true);
    readonly isArranging = signal<boolean>(false);

    markUnarranged(): void {
        this.hasUnarrangedChanges.set(true);
    }

    cancelAnimation(): void {
        if (this.arrangeAnimationId !== null) {
            cancelAnimationFrame(this.arrangeAnimationId);
            this.arrangeAnimationId = null;
        }
    }

    autoArrange(callbacks: ArrangeAnimatorCallbacks): void {
        if (this.arrangingLock || this.flowReadOnly.isReadOnly()) return;
        this.arrangingLock = true;
        this.isArranging.set(true);

        const nodes = this.flowService.nodes();
        if (nodes.length === 0) {
            this.resetLock(callbacks);
            return;
        }

        const connections = this.flowService.connections();
        const newPositions = computeLayout(nodes, connections);

        const alreadyArranged = nodes.every((node) => {
            const target = newPositions.get(node.id);
            return !target || (node.position.x === target.x && node.position.y === target.y);
        });
        // Arranging starts the wires over too: hand-edited points refer to the old node positions.
        const hasHandEditedWires = connections.some((conn) => conn.userAdjustedWaypoints);
        if (alreadyArranged && !hasHandEditedWires) {
            this.hasUnarrangedChanges.set(false);
            this.resetLock(callbacks);
            return;
        }

        this.undoRedoService.stateChanged();

        const startPositions = new Map(nodes.map((node) => [node.id, { ...node.position }]));

        // Clear ALL waypoints, hand-edited ones included, so every connection draws the builder's
        // fallback during the animation. The router runs once the nodes have landed.
        for (const conn of connections) {
            if (conn.waypoints?.length || conn.userAdjustedWaypoints) {
                this.flowService.updateConnectionWaypoints(conn.id, [], false);
            }
        }
        // Flush synchronously so nodes and arrows start from the same visual state.
        callbacks.detectChanges();
        callbacks.redraw();

        this.runAnimationLoop(nodes, newPositions, startPositions, callbacks);
    }

    private runAnimationLoop(
        nodes: NodeModel[],
        newPositions: Map<string, IPoint>,
        startPositions: Map<string, IPoint>,
        callbacks: ArrangeAnimatorCallbacks
    ): void {
        const DURATION = 400;
        const startTime = performance.now();

        const frame = (now: number): void => {
            const t = Math.min((now - startTime) / DURATION, 1);
            // ease-in-out quadratic
            const eased = t < 0.5 ? 2 * t * t : -1 + (4 - 2 * t) * t;

            const updatedNodes = nodes
                .filter((node) => newPositions.has(node.id))
                .map((node) => {
                    const from = startPositions.get(node.id) ?? node.position;
                    const to = newPositions.get(node.id)!;
                    return {
                        ...node,
                        position: {
                            x: Math.round(from.x + (to.x - from.x) * eased),
                            y: Math.round(from.y + (to.y - from.y) * eased),
                        },
                    };
                });

            this.flowService.updateNodesInBatch(updatedNodes);
            callbacks.detectChanges();
            callbacks.redraw();

            if (t < 1) {
                this.arrangeAnimationId = requestAnimationFrame(frame);
            } else {
                this.arrangeAnimationId = null;
                setTimeout(() => {
                    this.routingOrchestrator.rerouteSegmentConnections();
                    callbacks.detectChanges();
                    callbacks.redraw();
                    // Every node moved: bring the whole arranged flow into view.
                    callbacks.fitToScreen({ x: 200, y: 100 }, true);
                    this.hasUnarrangedChanges.set(false);
                    this.resetLock(callbacks);
                }, 0);
            }
        };

        this.arrangeAnimationId = requestAnimationFrame(frame);
    }

    private resetLock(callbacks: ArrangeAnimatorCallbacks): void {
        this.arrangingLock = false;
        this.isArranging.set(false);
        callbacks.detectChanges();
    }
}
