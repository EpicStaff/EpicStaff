import { computed, Injectable, signal } from '@angular/core';

import { EdgeDiffStatus, FlowDiffCanvasState, NodeDiffStatus, UnionNodeDiffState } from '../utils/diff';

/**
 * The diff status of each node and connection on a version diff canvas, by canvas id, and the nodes whose
 * version referenced something that no longer exists. The canvas (FlowGraphComponent) writes both together
 * with the flow it shows; nodes and connections read them for their status style and marker.
 *
 * The two are separate: the missing-reference marker shows on the plain version preview too, which has no
 * diff (no statuses, `isActive` false), so nothing else of the diff turns on there.
 *
 * Kept outside the node models on purpose: a status field on a node would leak into the save
 * comparables and the dirty check. `providedIn: 'root'` for the live editor, where it stays empty;
 * the version preview gets its own instance through FLOW_EDITOR_STATE_PROVIDERS.
 */
@Injectable({ providedIn: 'root' })
export class FlowDiffStateService {
    private readonly state = signal<FlowDiffCanvasState | null>(null);
    private readonly missingReferenceNodeIds = signal<ReadonlySet<string>>(new Set());

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

    /**
     * The node's whole diff (status, field changes, missing references) for its panel; `null` off a diff canvas
     * (the Preview tab, the live editor). The Preview tab only marks nodes with missing references
     * (`hasMissingReferences`); its warnings dialog lists the references.
     */
    public nodeDiff(nodeId: string): UnionNodeDiffState | null {
        return this.state()?.nodes.get(nodeId) ?? null;
    }

    /** Marks the nodes whose version referenced something that no longer exists (none in the live editor). */
    public setMissingReferenceNodeIds(nodeIds: ReadonlySet<string>): void {
        this.missingReferenceNodeIds.set(nodeIds);
    }

    /** Independent of the diff: also true on a plain version preview. */
    public hasMissingReferences(nodeId: string): boolean {
        return this.missingReferenceNodeIds().has(nodeId);
    }

    /** `null` for a connection that is not on a diff canvas. */
    public connectionStatus(connectionId: string): EdgeDiffStatus | null {
        return this.state()?.connections.get(connectionId) ?? null;
    }

    /**
     * The canvas id of the node a node reference in a field change names (its match key, `nodeRef`); `null` off a diff
     * canvas or for a key no node has.
     */
    public nodeIdOfKey(key: string): string | null {
        return this.state()?.nodeIdByKey.get(key) ?? null;
    }

    /** Whether only the version has this port of a node on both sides: a route a restore adds. */
    public isVersionOnlyPort(portId: string): boolean {
        return this.state()?.versionOnlyPortIds.has(portId) ?? false;
    }

    /** Whether only the current canvas has this route port of a node on both sides: a route a restore removes. */
    public isCurrentOnlyRoutePort(portId: string): boolean {
        return this.state()?.currentOnlyRoutePortIds.has(portId) ?? false;
    }
}
