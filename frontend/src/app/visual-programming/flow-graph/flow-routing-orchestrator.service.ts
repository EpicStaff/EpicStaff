import { computed, inject, Injectable, signal } from '@angular/core';
import { IPoint } from '@foblex/2d';

import { getPortPosition } from '../core/geometry/port-position';
import { isStacked } from '../core/geometry/wire-direction';
import { isBackwardConnection } from '../core/helpers/helpers';
import { ConnectionModel } from '../core/models/connection.model';
import { NodeModel } from '../core/models/node.model';
import { curveHitsObstacle } from '../core/routing/curved-obstacle-detection';
import { obstacleRect, routingObstacles } from '../core/routing/obstacles';
import { normalizeOrthogonalWaypoints, refreshFrozenWireWaypoints } from '../core/routing/orthogonal-route-shapes';
import { resolveWireEnds, routeAll } from '../core/routing/route-all';
import { FlowService } from '../services/flow.service';
import { FlowSettingsService } from '../services/flow-settings.service';

function waypointsEqual(a: IPoint[], b: IPoint[]): boolean {
    if (a.length !== b.length) return false;
    return a.every((p, i) => p.x === b[i].x && p.y === b[i].y);
}

/**
 * Handles routing orchestration for flow connections: backward-classification flips,
 * frozen wire refresh, A* routing, adaptive-curve obstacle checks, waypoint diffs,
 * and render-version bumping for change detection.
 */
@Injectable()
export class FlowRoutingOrchestratorService {
    private readonly flowService = inject(FlowService);
    private readonly flowSettings = inject(FlowSettingsService);

    /** Connection id -> backward at the last reroute. An id missing here has no classification to flip from. */
    private readonly previousBackwardClassification = new Map<string, boolean>();

    /** Edge style at the last reroute — a change clears user-adjusted waypoints. */
    private previousEdgeStyle: string | undefined;

    /** Tracks whether a waypoint drag is in progress for a given connection. */
    private readonly draggingWaypointConnectionIds = new Set<string>();

    /**
     * Render version per connection, used in the template's `track` expression
     * to force re-render when waypoints change without changing the connection id.
     */
    readonly connectionRenderVersions = signal<Record<string, number>>({});

    readonly backwardConnectionIds = computed<Set<string>>(() => {
        const nodes = this.flowService.nodes();
        const connections = this.flowService.visibleConnections();
        const ids = new Set<string>();

        for (const conn of connections) {
            if (isBackwardConnection(conn, nodes)) {
                ids.add(conn.id);
            }
        }

        return ids;
    });

    bumpConnectionRenderVersion(connectionId: string): void {
        this.connectionRenderVersions.update((v) => ({
            ...v,
            [connectionId]: (v[connectionId] ?? 0) + 1,
        }));
    }

    /** Clears backward classification tracking. Call when loading a new flow. */
    clearBackwardClassification(): void {
        this.previousBackwardClassification.clear();
    }

    /**
     * Main routing pipeline: backward-classification flip, frozen wire refresh,
     * routeAll(), adaptive-curve obstacle check, waypoint diff.
     */
    rerouteSegmentConnections(): void {
        const currentEdgeStyle = this.flowSettings.edgeStyle();
        const edgeStyleChanged = this.previousEdgeStyle && this.previousEdgeStyle !== currentEdgeStyle;
        this.previousEdgeStyle = currentEdgeStyle;

        if (edgeStyleChanged) {
            for (const conn of this.flowService.connections()) {
                if (conn.userAdjustedWaypoints) {
                    this.flowService.updateConnectionWaypoints(conn.id, [], false);
                    this.bumpConnectionRenderVersion(conn.id);
                }
            }
        }

        const backwardIds = this.backwardConnectionIds();
        for (const conn of this.flowService.connections()) {
            const previousBackward = this.previousBackwardClassification.get(conn.id);
            const classificationFlipped =
                previousBackward !== undefined && previousBackward !== backwardIds.has(conn.id);
            if (conn.userAdjustedWaypoints && classificationFlipped) {
                this.flowService.updateConnectionWaypoints(conn.id, [], false);
                this.bumpConnectionRenderVersion(conn.id);
            }
        }

        const nodes = this.flowService.nodes();
        const nodesById = new Map(nodes.map((node) => [node.id, node]));
        for (const conn of this.flowService.connections()) {
            if (!conn.userAdjustedWaypoints || !conn.waypoints?.length) continue;
            const ends = resolveWireEnds(conn, nodesById);
            if (!ends) continue;
            const source = getPortPosition(ends.sourceNode, ends.sourcePort);
            const target = getPortPosition(ends.targetNode, ends.targetPort);
            const refreshed = refreshFrozenWireWaypoints(source, conn.waypoints, target);
            if (!waypointsEqual(conn.waypoints, refreshed)) {
                this.flowService.updateConnectionWaypoints(conn.id, refreshed);
                this.bumpConnectionRenderVersion(conn.id);
            }
        }

        const connections = this.flowService.connections();
        const obstacleRects = [...routingObstacles(nodes).values()];
        const isAdaptiveCurve = this.flowSettings.edgeStyle() === 'adaptive-curve';
        const routes = routeAll(nodes, connections);
        for (const conn of connections) {
            const routePoints = routes.get(conn.id);
            let targetWaypoints = routePoints;

            // For adaptive-curve: only keep A* waypoints when the smooth curve would hit an obstacle.
            // When the curve is free, clear waypoints so the builder draws the smooth path.
            if (isAdaptiveCurve && routePoints && !conn.userAdjustedWaypoints) {
                const ends = resolveWireEnds(conn, nodesById);
                if (ends) {
                    const source = getPortPosition(ends.sourceNode, ends.sourcePort);
                    const target = getPortPosition(ends.targetNode, ends.targetPort);
                    const sourceBox = obstacleRect(ends.sourceNode);
                    const targetBox = obstacleRect(ends.targetNode);
                    const backwardReturnWire = target.x < source.x && !isStacked(sourceBox, targetBox);
                    targetWaypoints =
                        backwardReturnWire || curveHitsObstacle(source, target, obstacleRects) ? routePoints : [];
                }
            }

            if (targetWaypoints && !waypointsEqual(conn.waypoints ?? [], targetWaypoints)) {
                this.flowService.updateConnectionWaypoints(conn.id, targetWaypoints);
                this.bumpConnectionRenderVersion(conn.id);
            }
        }

        this.previousBackwardClassification.clear();
        for (const conn of connections) {
            this.previousBackwardClassification.set(conn.id, backwardIds.has(conn.id));
        }
    }

    /**
     * Processes a waypoint change event from the canvas. Handles drag-in-progress detection,
     * orthogonal normalization, and reset-to-router logic.
     */
    onWaypointsChanged(connectionId: string, waypoints: IPoint[]): void {
        const connection = this.flowService.connections().find((c: ConnectionModel) => c.id === connectionId);
        if (!connection) return;

        const existingCount = connection.waypoints?.length ?? 0;

        // A candidate insert starts a drag. Do NOT update the Angular signal here -- pushing
        // a new waypoints array back to Foblex via [waypoints] would overwrite the internal
        // reference that the drag handler mutates on every mousemove, killing the preview.
        // Instead, just track the connection ID so the release event below is recognized.
        if (!this.draggingWaypointConnectionIds.has(connectionId) && waypoints.length > existingCount) {
            this.draggingWaypointConnectionIds.add(connectionId);
            return;
        }

        // Release: drag ended or a right-click removed a bend.
        this.draggingWaypointConnectionIds.delete(connectionId);

        const nodesById = new Map(this.flowService.nodes().map((node: NodeModel) => [node.id, node]));
        const ends = resolveWireEnds(connection, nodesById);
        const normalizedWaypoints = ends
            ? normalizeOrthogonalWaypoints(
                  getPortPosition(ends.sourceNode, ends.sourcePort),
                  waypoints,
                  getPortPosition(ends.targetNode, ends.targetPort)
              )
            : waypoints;
        // A right-click that removes a bend the orthogonal shape can't do without (normalizing puts it
        // straight back) resets the wire to automatic routing, as removing the last point does.
        const isResetToRouter =
            normalizedWaypoints.length === 0 ||
            (waypoints.length < existingCount && waypointsEqual(normalizedWaypoints, connection.waypoints ?? []));
        this.flowService.updateConnectionWaypoints(
            connectionId,
            isResetToRouter ? [] : normalizedWaypoints,
            !isResetToRouter
        );

        // The other wires make room for the edited one (it now occupies its corridor); a reset wire
        // is the router's again.
        this.rerouteSegmentConnections();
    }
}
