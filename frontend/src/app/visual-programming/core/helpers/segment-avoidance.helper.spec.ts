import { IPoint } from '@foblex/2d';

import { NodeType } from '../enums/node-type';
import { ConnectionModel } from '../models/connection.model';
import { NodeModel } from '../models/node.model';
import { computeSegmentAvoidanceWaypoints, pathSelfIntersects } from './segment-avoidance.helper';

function pt(x: number, y: number): IPoint {
    return { x, y };
}

function node(
    id: string,
    x: number,
    y: number,
    width: number,
    height: number,
    ports: { id: string; position: string }[] = []
): NodeModel {
    return {
        id,
        type: NodeType.AGENT,
        position: { x, y },
        size: { width, height },
        ports,
        data: null,
    } as unknown as NodeModel;
}

describe('pathSelfIntersects', () => {
    it('detects a self-crossing 4-point path (bowtie)', () => {
        const path = [pt(0, 0), pt(10, 10), pt(10, 0), pt(0, 10)];

        expect(pathSelfIntersects(path)).toBe(true);
    });

    it('accepts a normal orthogonal zigzag with no self-crossing', () => {
        const path = [pt(0, 0), pt(0, 10), pt(20, 10), pt(20, 20)];

        expect(pathSelfIntersects(path)).toBe(false);
    });

    it('flags a path whose later segment doubles back onto an earlier one', () => {
        const path = [pt(0, 0), pt(20, 0), pt(20, 10), pt(5, 0)];

        expect(pathSelfIntersects(path)).toBe(true);
    });

    it('does not flag two adjacent segments sharing an endpoint', () => {
        const path = [pt(0, 0), pt(10, 0), pt(10, 10)];

        expect(pathSelfIntersects(path)).toBe(false);
    });
});

describe('computeSegmentAvoidanceWaypoints', () => {
    it('never returns a self-crossing path when detouring around a blocking node', () => {
        const source = node('source', 0, 0, 100, 60, [{ id: 'source_out-right', position: 'right' }]);
        const target = node('target', 400, 200, 100, 60, [{ id: 'target_in-left', position: 'left' }]);
        const blocker = node('blocker', 200, -50, 100, 340);

        const connection = {
            id: 'conn-1',
            sourceNodeId: 'source',
            targetNodeId: 'target',
            sourcePortId: 'source_out-right',
            targetPortId: 'target_in-left',
        } as unknown as ConnectionModel;

        const waypoints = computeSegmentAvoidanceWaypoints(connection, [source, target, blocker]);

        expect(waypoints).not.toBeNull();

        const sourcePt = pt(100, 30);
        const targetPt = pt(400, 230);
        const fullPath = [sourcePt, ...(waypoints ?? []), targetPt];

        expect(pathSelfIntersects(fullPath)).toBe(false);
    });

    it('never routes the exit/entry stub backward through the source or target node itself', () => {
        const a = node('a', 110, 275, 240, 45, [{ id: 'a_out', position: 'right' }]);
        const b = node('b', 120, 340, 230, 45, [
            { id: 'b_out', position: 'right' },
            { id: 'b_in', position: 'left' },
        ]);
        const c = node('c', 185, 405, 230, 45, [{ id: 'c_in', position: 'left' }]);

        const connection = {
            id: 'conn-1',
            sourceNodeId: 'a',
            targetNodeId: 'c',
            sourcePortId: 'a_out',
            targetPortId: 'c_in',
        } as unknown as ConnectionModel;

        const waypoints = computeSegmentAvoidanceWaypoints(connection, [a, b, c]);

        expect(waypoints).not.toBeNull();
        expect(waypoints!.length).toBeGreaterThan(0);

        const sourcePt = pt(350, 297.5);
        const targetPt = pt(185, 427.5);

        expect(waypoints![0].x).toBeGreaterThanOrEqual(sourcePt.x);
        expect(waypoints![waypoints!.length - 1].x).toBeLessThanOrEqual(targetPt.x);

        const fullPath = [sourcePt, ...(waypoints ?? []), targetPt];
        expect(pathSelfIntersects(fullPath)).toBe(false);
    });

    it('routes over the top of the source node when a right-port source sits directly above a west-of-it left-port target, even with no third-node blocker in between', () => {
        const source = node('source', 100, 100, 330, 60, [{ id: 'source_out', position: 'right' }]);
        const target = node('target', 100, 240, 330, 60, [{ id: 'target_in', position: 'left' }]);

        const connection = {
            id: 'conn-1',
            sourceNodeId: 'source',
            targetNodeId: 'target',
            sourcePortId: 'source_out',
            targetPortId: 'target_in',
        } as unknown as ConnectionModel;

        const waypoints = computeSegmentAvoidanceWaypoints(connection, [source, target]);

        expect(waypoints).not.toBeNull();
        expect(waypoints!.length).toBeGreaterThan(0);

        const sourcePt = pt(430, 130);
        const targetPt = pt(100, 270);
        const fullPath = [sourcePt, ...(waypoints ?? []), targetPt];

        const cutsThroughSource = fullPath.some(
            (p, i) =>
                i < fullPath.length - 1 &&
                fullPath[i].y === fullPath[i + 1].y &&
                fullPath[i].y >= 100 &&
                fullPath[i].y <= 160 &&
                Math.min(fullPath[i].x, fullPath[i + 1].x) < 430 &&
                Math.max(fullPath[i].x, fullPath[i + 1].x) > 100
        );
        expect(cutsThroughSource).toBe(false);
        expect(pathSelfIntersects(fullPath)).toBe(false);
    });

    it('returns an empty array (not null) when no existing waypoints are given and the default route is already clean', () => {
        const source = node('source', 0, 0, 100, 60, [{ id: 'source_out-right', position: 'right' }]);
        const target = node('target', 300, 200, 100, 60, [{ id: 'target_in-left', position: 'left' }]);

        const connection = {
            id: 'conn-1',
            sourceNodeId: 'source',
            targetNodeId: 'target',
            sourcePortId: 'source_out-right',
            targetPortId: 'target_in-left',
        } as unknown as ConnectionModel;

        const waypoints = computeSegmentAvoidanceWaypoints(connection, [source, target], undefined);

        expect(waypoints).not.toBeNull();
        expect(waypoints).toEqual([]);
    });

    it('returns the clean default path even when an unrelated node is merely near (not actually crossing) it', () => {
        const source = node('source', 100, 100, 330, 60, [{ id: 'source_out', position: 'right' }]);
        const stacked = node('stacked', 100, 220, 330, 60, []);
        const target = node('target', 500, 145, 330, 60, [{ id: 'target_in', position: 'left' }]);

        const connection = {
            id: 'conn-1',
            sourceNodeId: 'source',
            targetNodeId: 'target',
            sourcePortId: 'source_out',
            targetPortId: 'target_in',
        } as unknown as ConnectionModel;

        const waypoints = computeSegmentAvoidanceWaypoints(connection, [source, stacked, target], undefined);

        expect(waypoints).not.toBeNull();
        expect(waypoints).toEqual([]);
    });

    it('simplifies a stale reused "box" detour back to the clean default path once it is no longer needed', () => {
        const source = node('source', 100, 260, 330, 60, [{ id: 'source_out', position: 'right' }]);
        const nearby = node('nearby', 100, 380, 330, 60, []);
        const target = node('target', 500, 330, 330, 60, [{ id: 'target_in', position: 'left' }]);

        const connection = {
            id: 'conn-1',
            sourceNodeId: 'source',
            targetNodeId: 'target',
            sourcePortId: 'source_out',
            targetPortId: 'target_in',
        } as unknown as ConnectionModel;

        const staleBoxWaypoints: IPoint[] = [
            pt(460, 280),
            pt(460, 180),
            pt(560, 180),
            pt(560, 280),
            pt(480, 280),
            pt(480, 340),
        ];

        const waypoints = computeSegmentAvoidanceWaypoints(connection, [source, nearby, target], staleBoxWaypoints);

        expect(waypoints).not.toBeNull();
        expect(waypoints).toEqual([]);
    });
});
