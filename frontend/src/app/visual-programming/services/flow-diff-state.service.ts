import { computed, Injectable, signal } from '@angular/core';

import { EdgeDiffStatus, FlowDiffCanvasState, NodeDiffStatus } from '../utils/diff';

/**
 * The diff status of each node and connection on a version diff canvas, by canvas id. The canvas
 * (FlowGraphComponent) writes it together with the union flow it shows; nodes and connections read it
 * for their status style.
 *
 * Kept outside the node models on purpose: a status field on a node would leak into the save
 * comparables and the dirty check. `providedIn: 'root'` for the live editor, where it stays empty;
 * the version preview gets its own instance through FLOW_EDITOR_STATE_PROVIDERS.
 */
@Injectable({ providedIn: 'root' })
export class FlowDiffStateService {
    private readonly state = signal<FlowDiffCanvasState | null>(null);

    /** Whether the canvas shows a diff. False in the live editor and in a plain preview. */
    public readonly isActive = computed(() => this.state() !== null);

    /** Shows the statuses of a new diff canvas, or none (`null`) for a plain canvas. */
    public setState(state: FlowDiffCanvasState | null): void {
        this.state.set(state);
    }

    /** `null` for a node that is not on a diff canvas. */
    public nodeStatus(nodeId: string): NodeDiffStatus | null {
        return this.state()?.nodes.get(nodeId)?.status ?? null;
    }

    public hasMissingReferences(nodeId: string): boolean {
        return this.state()?.nodes.get(nodeId)?.hasMissingReferences ?? false;
    }

    /** `null` for a connection that is not on a diff canvas. */
    public connectionStatus(connectionId: string): EdgeDiffStatus | null {
        return this.state()?.connections.get(connectionId) ?? null;
    }

    /** Whether only the version has this port of a node on both sides: a route a restore adds. */
    public isVersionOnlyPort(portId: string): boolean {
        return this.state()?.versionOnlyPortIds.has(portId) ?? false;
    }
}
