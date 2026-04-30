import { IPoint } from '@foblex/2d';

import { ConnectionModel } from '../../core/models/connection.model';

export function hasPersistedWaypoints(conn: ConnectionModel): boolean {
    return conn.userAdjustedWaypoints === true && (conn.waypoints?.length ?? 0) > 0;
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
