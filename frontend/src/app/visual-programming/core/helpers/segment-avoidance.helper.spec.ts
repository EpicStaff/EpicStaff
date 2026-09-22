import { IPoint } from '@foblex/2d';

import { NodeType } from '../enums/node-type';
import { ConnectionModel } from '../models/connection.model';
import { NodeModel } from '../models/node.model';
import { ViewPort } from '../models/port.model';
import { computeSegmentAvoidanceWaypoints, getPortPosition, pathSelfIntersects } from './segment-avoidance.helper';

// Axis-aligned segment vs. a node's true (unpadded) body — used to assert the route never
// visually cuts through a node, as opposed to grazing its routing-collision padding.
function segmentEntersBody(a: IPoint, b: IPoint, n: NodeModel): boolean {
    const box = {
        left: n.position.x,
        top: n.position.y,
        right: n.position.x + n.size.width,
        bottom: n.position.y + n.size.height,
    };
    if (a.x === b.x) {
        if (a.x <= box.left || a.x >= box.right) return false;
        return Math.max(a.y, b.y) > box.top && Math.min(a.y, b.y) < box.bottom;
    }
    if (a.y === b.y) {
        if (a.y <= box.top || a.y >= box.bottom) return false;
        return Math.max(a.x, b.x) > box.left && Math.min(a.x, b.x) < box.right;
    }
    return false;
}

function pt(x: number, y: number): IPoint {
    return { x, y };
}

function dtGroup(groupName: string, order: number) {
    return {
        group_name: groupName,
        group_type: 'simple',
        expression: null,
        conditions: [],
        manipulation: null,
        next_node: null,
        valid: true,
        order,
    };
}

function dtTableNode(
    id: string,
    x: number,
    y: number,
    height: number,
    groupNames: string[],
    ports: { id: string; role: string }[]
): NodeModel {
    return {
        id,
        type: NodeType.TABLE,
        position: { x, y },
        size: { width: 330, height },
        ports,
        data: { name: id, table: { condition_groups: groupNames.map((name, i) => dtGroup(name, i)) } },
    } as unknown as NodeModel;
}

function cdtRouteGroup(routeCode: string, order: number) {
    return {
        group_name: routeCode,
        group_type: 'simple',
        expression: null,
        conditions: [],
        manipulation: null,
        next_node: null,
        valid: true,
        dock_visible: true,
        route_code: routeCode,
        order,
    };
}

function cdtTableNode(
    id: string,
    x: number,
    y: number,
    height: number,
    routeCodes: string[],
    ports: { id: string; role: string; position: string }[]
): NodeModel {
    return {
        id,
        type: NodeType.CLASSIFICATION_TABLE,
        position: { x, y },
        size: { width: 330, height },
        ports,
        data: { name: id, table: { condition_groups: routeCodes.map((code, i) => cdtRouteGroup(code, i)) } },
    } as unknown as NodeModel;
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

    it('detours around the source node instead of cutting through it when a right-port source sits directly above a west-of-it left-port target, taking the shorter of the two clearances (under, in this geometry), even with no third-node blocker in between', () => {
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

        // The over-the-top route is valid too, but loses the length tie-break: 950 vs 750.
        const detoursBelowSource = fullPath.some(
            (p, i) =>
                i < fullPath.length - 1 &&
                fullPath[i].y === fullPath[i + 1].y &&
                fullPath[i].y > 160 &&
                Math.min(fullPath[i].x, fullPath[i + 1].x) < 100 &&
                Math.max(fullPath[i].x, fullPath[i + 1].x) > 430
        );
        expect(detoursBelowSource).toBe(true);

        expect(pathSelfIntersects(fullPath)).toBe(false);
    });

    it("does not force a large overhead detour when the default midpoint only grazes the source node's collision padding, not its actual body", () => {
        const source = node('source', 260, -200, 330, 60, [{ id: 'source_out', position: 'right' }]);
        const target = node('target', 600, -80, 330, 60, [{ id: 'target_in', position: 'left' }]);

        const connection = {
            id: 'conn-1',
            sourceNodeId: 'source',
            targetNodeId: 'target',
            sourcePortId: 'source_out',
            targetPortId: 'target_in',
        } as unknown as ConnectionModel;

        const waypoints = computeSegmentAvoidanceWaypoints(connection, [source, target], undefined);

        expect(waypoints).not.toBeNull();
        expect(waypoints).toEqual([]);
    });

    it('hugs the real blocker instead of sweeping past the source/target tops when a gap already clears them', () => {
        const source = node('source', 140, 620, 330, 60, [{ id: 'source_out', position: 'right' }]);
        const target = node('target', 480, 1000, 330, 60, [{ id: 'target_in', position: 'left' }]);
        const blocker = node('blocker', 280, 880, 330, 60, []);

        const connection = {
            id: 'conn-1',
            sourceNodeId: 'source',
            targetNodeId: 'target',
            sourcePortId: 'source_out',
            targetPortId: 'target_in',
        } as unknown as ConnectionModel;

        const waypoints = computeSegmentAvoidanceWaypoints(connection, [source, blocker, target], undefined);

        expect(waypoints).not.toBeNull();
        expect(waypoints!.length).toBeGreaterThan(0);

        const jogY = waypoints![1].y;
        expect(jogY).toBeGreaterThan(710);
        expect(jogY).toBeLessThan(850);

        const sourcePt = pt(470, 650);
        const targetPt = pt(480, 1030);
        const fullPath = [sourcePt, ...(waypoints ?? []), targetPt];
        expect(pathSelfIntersects(fullPath)).toBe(false);
    });

    it('falls back to full clearance instead of the tight jog when the gap next to source/target is too small', () => {
        const source = node('source', 100, 100, 330, 60, [{ id: 'source_out', position: 'right' }]);
        const blocker = node('blocker', 250, 170, 330, 400);
        const target = node('target', 250, 620, 330, 60, [{ id: 'target_in', position: 'left' }]);

        const connection = {
            id: 'conn-1',
            sourceNodeId: 'source',
            targetNodeId: 'target',
            sourcePortId: 'source_out',
            targetPortId: 'target_in',
        } as unknown as ConnectionModel;

        const waypoints = computeSegmentAvoidanceWaypoints(connection, [source, blocker, target], undefined);

        expect(waypoints).not.toBeNull();

        const sourcePt = pt(430, 130);
        const targetPt = pt(250, 650);
        const fullPath = [sourcePt, ...(waypoints ?? []), targetPt];
        expect(pathSelfIntersects(fullPath)).toBe(false);
    });

    it('still clears all nodes when a second, unrelated node also occupies the tight gap the jog would otherwise use', () => {
        const source = node('source', 140, 620, 330, 60, [{ id: 'source_out', position: 'right' }]);
        const target = node('target', 480, 1000, 330, 60, [{ id: 'target_in', position: 'left' }]);
        const blocker = node('blocker', 280, 880, 330, 60);
        const secondBlocker = node('second', 280, 760, 330, 40);

        const connection = {
            id: 'conn-1',
            sourceNodeId: 'source',
            targetNodeId: 'target',
            sourcePortId: 'source_out',
            targetPortId: 'target_in',
        } as unknown as ConnectionModel;

        const waypoints = computeSegmentAvoidanceWaypoints(
            connection,
            [source, target, blocker, secondBlocker],
            undefined
        );

        expect(waypoints).not.toBeNull();

        const sourcePt = pt(470, 650);
        const targetPt = pt(480, 1030);
        const fullPath = [sourcePt, ...(waypoints ?? []), targetPt];
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

describe('getPortPosition — plain Decision Table row geometry', () => {
    it('resolves a DT output port by group_name after a reorder, not by its stored ports-array position', () => {
        // Ports were generated when 'alpha' was order 0 and 'beta' was order 1 — that array
        // order never changes on a pure reorder (normalize-flow-ports only regenerates on a
        // port-count change). The groups have since been reordered: beta is now order 0.
        const ports = [
            { id: 'dt_table-in', role: 'table-in' },
            { id: 'dt_decision-out-alpha', role: 'decision-out-alpha' },
            { id: 'dt_decision-out-beta', role: 'decision-out-beta' },
        ];
        const dt = dtTableNode('dt', 0, 0, 300, ['beta', 'alpha'], ports);

        const alphaPort = ports[1] as unknown as ViewPort;
        const betaPort = ports[2] as unknown as ViewPort;

        expect(getPortPosition(dt, alphaPort).y).toBe(60 + 60 * 1 + 30);
        expect(getPortPosition(dt, betaPort).y).toBe(60 + 60 * 0 + 30);
    });

    it('places the DT input port at y + 28 (the .input-port-wrapper centre), not the body middle', () => {
        const ports = [{ id: 'dt_table-in', role: 'table-in' }];
        const dt = dtTableNode('dt', 100, 200, 300, [], ports);

        const inputPort = ports[0] as unknown as ViewPort;

        expect(getPortPosition(dt, inputPort)).toEqual({ x: 100, y: 228 });
    });
});

describe('computeSegmentAvoidanceWaypoints — flow-4 regression (python #3 -> DT#10)', () => {
    it(
        'takes the plain two-bend corridor route instead of dead-ending into null when the only ' +
            'near miss is a port-adjacent sibling grazing the exit stub',
        () => {
            const dtPorts = [{ id: 'dt10_table-in', role: 'table-in', position: 'left' }];
            const dt10 = dtTableNode('dt10', 2140, 390, 300, ['g1', 'g2'], dtPorts);

            const p3 = node('p3', 1580, 290, 330, 60, [{ id: 'p3_out', position: 'right' }]);
            const end = node('end', 1580, 390, 330, 60);
            const audioToText = node('audio9', 2140, 270, 330, 60);
            const fileExtractor = node('file8', 2140, 170, 330, 60);
            const n1 = node('n1', 1580, 170, 330, 60);
            // Zero vertical gap to p3 (230+60=290=p3's top) — its padded bottom edge grazes p3's
            // output-port height exactly, which is the near-miss this fixture reproduces.
            const n2 = node('n2', 1580, 230, 330, 60);
            const cdt11 = node('cdt11', 920, 110, 330, 360);
            const n7 = node('n7', 400, 250, 330, 60);
            const start = node('start', 100, 250, 125, 60);
            const n4 = node('n4', 2800, 450, 330, 60);
            const n5 = node('n5', 2800, 510, 330, 60);
            const n6 = node('n6', 2800, 570, 330, 60);

            const allNodes = [p3, dt10, end, audioToText, fileExtractor, n1, n2, cdt11, n7, start, n4, n5, n6];

            const connection = {
                id: 'conn-p3-dt10',
                sourceNodeId: 'p3',
                targetNodeId: 'dt10',
                sourcePortId: 'p3_out',
                targetPortId: 'dt10_table-in',
            } as unknown as ConnectionModel;

            const waypoints = computeSegmentAvoidanceWaypoints(connection, allNodes, undefined);

            expect(waypoints).not.toBeNull();
            expect(waypoints).toEqual([]);

            const sourcePt = getPortPosition(p3, p3.ports![0] as unknown as ViewPort);
            const targetPt = getPortPosition(dt10, dtPorts[0] as unknown as ViewPort);
            const fullPath = [sourcePt, ...(waypoints ?? []), targetPt];

            for (let i = 1; i < fullPath.length; i++) {
                expect(fullPath[i].x).toBeGreaterThanOrEqual(fullPath[i - 1].x);
            }

            for (const p of fullPath) {
                expect(p.x).toBeGreaterThanOrEqual(sourcePt.x);
                expect(p.x).toBeLessThanOrEqual(targetPt.x);
            }

            const otherNodes = allNodes.filter((n) => n.id !== 'p3' && n.id !== 'dt10');
            for (let i = 1; i < fullPath.length; i++) {
                for (const n of otherNodes) {
                    expect(segmentEntersBody(fullPath[i - 1], fullPath[i], n)).toBe(false);
                }
            }
        }
    );
});

describe('computeSegmentAvoidanceWaypoints — CDT Default row to an End node below and right', () => {
    it('routes underneath the blockers instead of climbing back over the whole table', () => {
        const cdtPorts = [
            { id: 'cdt_table-in', role: 'table-in', position: 'left' },
            { id: 'cdt_decision-route-a', role: 'decision-route-a', position: 'right' },
            { id: 'cdt_decision-route-b', role: 'decision-route-b', position: 'right' },
            { id: 'cdt_decision-route-c', role: 'decision-route-c', position: 'right' },
            { id: 'cdt_decision-route-d', role: 'decision-route-d', position: 'right' },
            { id: 'cdt_decision-default', role: 'decision-default', position: 'right' },
            { id: 'cdt_decision-error', role: 'decision-error', position: 'right' },
        ];
        const cdt = cdtTableNode('cdt', 80, 130, 420, ['a', 'b', 'c', 'd'], cdtPorts);
        const end = node('end', 1000, 740, 330, 60, [{ id: 'end_in', position: 'left' }]);
        const py1 = node('py1', 560, 500, 330, 60);
        const py2 = node('py2', 560, 570, 330, 60);
        const py3 = node('py3', 560, 640, 330, 60);
        const allNodes = [cdt, end, py1, py2, py3];

        const connection = {
            id: 'conn-default-end',
            sourceNodeId: 'cdt',
            targetNodeId: 'end',
            sourcePortId: 'cdt_decision-default',
            targetPortId: 'end_in',
        } as unknown as ConnectionModel;

        const waypoints = computeSegmentAvoidanceWaypoints(connection, allNodes, undefined);

        expect(waypoints).not.toBeNull();
        expect(waypoints!.length).toBeGreaterThan(0);

        const sourcePt = getPortPosition(cdt, cdtPorts[5] as unknown as ViewPort);
        const targetPt = getPortPosition(end, end.ports![0] as unknown as ViewPort);
        const fullPath = [sourcePt, ...(waypoints ?? []), targetPt];

        const tableTop = cdt.position.y;
        for (const p of fullPath) {
            expect(p.y).toBeGreaterThanOrEqual(tableTop);
        }

        const manhattan = Math.abs(targetPt.x - sourcePt.x) + Math.abs(targetPt.y - sourcePt.y);
        const length = fullPath
            .slice(0, -1)
            .reduce((s, p, i) => s + Math.abs(fullPath[i + 1].x - p.x) + Math.abs(fullPath[i + 1].y - p.y), 0);
        expect(length).toBeLessThanOrEqual(manhattan * 1.8);

        expect(pathSelfIntersects(fullPath)).toBe(false);

        const otherNodes = allNodes.filter((n) => n.id !== 'cdt' && n.id !== 'end');
        for (let i = 1; i < fullPath.length; i++) {
            for (const n of otherNodes) {
                expect(segmentEntersBody(fullPath[i - 1], fullPath[i], n)).toBe(false);
            }
        }
    });
});
