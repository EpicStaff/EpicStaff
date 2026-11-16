import { IPoint } from '@foblex/2d';

import { ConnectionModel } from '../../core/models/connection.model';
import { FlowModel } from '../../core/models/flow.model';

export function hasPersistedWaypoints(conn: ConnectionModel): boolean {
    return conn.userAdjustedWaypoints === true && (conn.waypoints?.length ?? 0) > 0;
}

/** Whether the edge row this connection was loaded from holds bends (whether or not the canvas uses them). */
export function hasStoredWaypoints(conn: ConnectionModel): boolean {
    const stored = conn.data?.metadata?.['waypoints'];
    return Array.isArray(stored) && stored.length > 0;
}

/** The bends an edge save writes: the hand-placed ones, or none for a wire the router draws. */
export function waypointsToPersist(conn: ConnectionModel): IPoint[] {
    return hasPersistedWaypoints(conn) ? conn.waypoints! : [];
}

/**
 * Strips `waypoints` from non-user-adjusted connections, mirroring `hasPersistedWaypoints`:
 * those waypoints are router-computed and never saved, so they must not count as unsaved changes.
 */
export function toDirtyComparableFlowState(flow: FlowModel): FlowModel {
    return {
        nodes: flow.nodes,
        connections: flow.connections.map((conn) => {
            if (conn.userAdjustedWaypoints === true) return conn;
            const rest: ConnectionModel = { ...conn };
            delete rest.waypoints;
            return rest;
        }),
    };
}

export function waypointsChanged(prev: IPoint[] | undefined, curr: IPoint[] | undefined): boolean {
    if ((prev?.length ?? 0) !== (curr?.length ?? 0)) return true;
    return JSON.stringify(prev ?? []) !== JSON.stringify(curr ?? []);
}

export function mergeWaypointsIntoMetadata(
    existingMetadata: Record<string, unknown>,
    waypoints: IPoint[]
): Record<string, unknown> {
    return { ...existingMetadata, waypoints };
}
