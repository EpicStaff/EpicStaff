import { IPoint } from '@foblex/2d';

import { measure, RoutedWire } from '../layout/quality/metrics';
import { nudgePaths, RoutedPath } from './nudging';
import { Rect } from './obstacles';

// Padded boxes of a source column (x 0..330) and a target column (x 800..1130), as the router sees them.
const SOURCE_COLUMN: Rect = { left: -15, top: -15, right: 345, bottom: 75 };

function path(id: string, points: IPoint[], sourcePortKey = `${id}_out`, targetPortKey = `${id}_in`): RoutedPath {
    return { id, sourcePortKey, targetPortKey, points };
}

// Crossings and collinear overlaps between the paths, measured by the quality checker.
function report(paths: RoutedPath[]): { crossings: number; collinearOverlaps: number } {
    const wires: RoutedWire[] = paths.map((routed) => ({
        ...routed,
        sourceNodeId: `${routed.id}-source`,
        targetNodeId: `${routed.id}-target`,
    }));
    const { crossings, collinearOverlaps } = measure([], wires);
    return { crossings, collinearOverlaps };
}

function verticalXs(points: IPoint[]): number[] {
    return points.slice(1).flatMap((point, index) => (point.x === points[index].x ? [point.x] : []));
}

describe('nudgePaths', () => {
    it('spreads parallel risers of unrelated wires that run 2 px apart into lanes', () => {
        // Not collinear, so no collinear overlap, but drawn 2 px apart they read as one thick wire.
        const paths = [
            path('a', [
                { x: 335, y: 30 },
                { x: 560, y: 30 },
                { x: 560, y: 330 },
                { x: 795, y: 330 },
            ]),
            path('b', [
                { x: 335, y: 100 },
                { x: 562, y: 100 },
                { x: 562, y: 400 },
                { x: 795, y: 400 },
            ]),
        ];

        const [first, second] = nudgePaths(paths, []);

        // b turns up from y 100 before a comes down to 330, so b takes the left lane: that also undoes
        // the two crossings the 2-px pair had.
        const [firstX] = verticalXs(first.points);
        const [secondX] = verticalXs(second.points);
        expect(firstX - secondX).toBeGreaterThanOrEqual(10);
        expect(report(paths).crossings).toBe(2);
        expect(report([first, second])).toEqual({ crossings: 0, collinearOverlaps: 0 });
    });

    it('lays a wire out beside a fixed (hand-edited) one, which keeps its line', () => {
        // The edited riser at x 560 (y 30..330); the routed one shares it (y 100..400) and can't go
        // right: its target stub starts at 560.
        const edited = path('edited', [
            { x: 335, y: 30 },
            { x: 560, y: 30 },
            { x: 560, y: 330 },
            { x: 800, y: 330 },
        ]);
        const routed = path('routed', [
            { x: 335, y: 100 },
            { x: 560, y: 100 },
            { x: 560, y: 400 },
            { x: 580, y: 400 },
        ]);

        const [nudged, ...rest] = nudgePaths([routed], [], [edited]);

        expect(rest).toEqual([]); // fixed wires are context, not output
        expect(verticalXs(nudged.points)).toEqual([550]);
        expect(report([nudged, edited]).collinearOverlaps).toBe(0);
        // Without it as context, nothing tells the routed wire the lane is taken.
        expect(verticalXs(nudgePaths([routed], [])[0].points)).toEqual([560]);
    });

    it('gives two wires sharing no port their own lanes even when a third shares a port with each', () => {
        // a and b leave one source port, b and c enter one target port; a and c share nothing but
        // the riser at x 560 (from y 230 to 330).
        const paths = [
            path(
                'a',
                [
                    { x: 335, y: 30 },
                    { x: 560, y: 30 },
                    { x: 560, y: 330 },
                    { x: 795, y: 330 },
                ],
                's1_out',
                't1_in'
            ),
            path(
                'b',
                [
                    { x: 335, y: 30 },
                    { x: 560, y: 30 },
                    { x: 560, y: 450 },
                    { x: 795, y: 450 },
                ],
                's1_out',
                't2_in'
            ),
            path(
                'c',
                [
                    { x: 335, y: 230 },
                    { x: 560, y: 230 },
                    { x: 560, y: 450 },
                    { x: 795, y: 450 },
                ],
                's2_out',
                't2_in'
            ),
        ];
        expect(report(paths).collinearOverlaps).toBe(1);

        const nudged = nudgePaths(paths, []);

        expect(report(nudged).collinearOverlaps).toBe(0);
    });

    it('separates two wires from different sources that share a riser, without a crossing', () => {
        const paths = [
            path('a', [
                { x: 335, y: 30 },
                { x: 560, y: 30 },
                { x: 560, y: 330 },
                { x: 795, y: 330 },
            ]),
            path('b', [
                { x: 335, y: 230 },
                { x: 560, y: 230 },
                { x: 560, y: 450 },
                { x: 795, y: 450 },
            ]),
        ];
        expect(report(paths).collinearOverlaps).toBe(1);

        const nudged = nudgePaths(paths, []);

        expect(report(nudged)).toEqual({ crossings: 0, collinearOverlaps: 0 });
        const [riserA] = verticalXs(nudged[0].points);
        const [riserB] = verticalXs(nudged[1].points);
        expect(Math.abs(riserA - riserB)).toBeGreaterThanOrEqual(10);
        expect(nudged.map((routed) => routed.id)).toEqual(['a', 'b']);
    });

    it('fans three stacked wires into three stacked targets without crossings', () => {
        const paths = [0, 1, 2].map((index) =>
            path(`w${index}`, [
                { x: 335, y: 30 + index * 100 },
                { x: 560, y: 30 + index * 100 },
                { x: 560, y: 330 + index * 100 },
                { x: 795, y: 330 + index * 100 },
            ])
        );

        const nudged = nudgePaths(paths, []);

        expect(report(nudged)).toEqual({ crossings: 0, collinearOverlaps: 0 });
        const risers = nudged.map((routed) => verticalXs(routed.points)[0]);
        expect(new Set(risers).size).toBe(3);
    });

    it('leaves a trunk of two wires from the same source port together', () => {
        const paths = [
            path(
                'a',
                [
                    { x: 335, y: 30 },
                    { x: 560, y: 30 },
                    { x: 560, y: 330 },
                    { x: 795, y: 330 },
                ],
                'shared_out'
            ),
            path(
                'b',
                [
                    { x: 335, y: 30 },
                    { x: 560, y: 30 },
                    { x: 560, y: 450 },
                    { x: 795, y: 450 },
                ],
                'shared_out'
            ),
        ];

        expect(nudgePaths(paths, [])).toEqual(paths);
    });

    it('narrows the lanes in a 12-px channel without entering the walls or overlapping', () => {
        const walls: Rect[] = [
            { left: 400, top: 0, right: 554, bottom: 500 },
            { left: 566, top: 0, right: 700, bottom: 500 },
        ];
        const paths = [
            path('a', [
                { x: 335, y: -30 },
                { x: 560, y: -30 },
                { x: 560, y: 540 },
                { x: 795, y: 540 },
            ]),
            path('b', [
                { x: 335, y: -60 },
                { x: 560, y: -60 },
                { x: 560, y: 520 },
                { x: 795, y: 520 },
            ]),
        ];

        const nudged = nudgePaths(paths, walls);

        const risers = nudged.map((routed) => verticalXs(routed.points)[0]);
        const spacing = Math.abs(risers[0] - risers[1]);
        expect(spacing).toBeGreaterThan(0);
        expect(spacing).toBeLessThan(10);
        expect(risers.every((x) => x >= 554 && x <= 566)).toBe(true);
        expect(report(nudged)).toEqual({ crossings: 0, collinearOverlaps: 0 });
    });

    it('keeps the stubs on their port y and the risers at least 20 px from the ports', () => {
        // Two sources in one column, both turning right at their 20-px stub ends (x 355).
        const paths = [
            path('a', [
                { x: 335, y: 30 },
                { x: 355, y: 30 },
                { x: 355, y: 330 },
                { x: 795, y: 330 },
            ]),
            path('b', [
                { x: 335, y: 230 },
                { x: 355, y: 230 },
                { x: 355, y: 450 },
                { x: 795, y: 450 },
            ]),
        ];

        const nudged = nudgePaths(paths, [SOURCE_COLUMN]);

        expect(report(nudged).collinearOverlaps).toBe(0);
        for (const [index, routed] of nudged.entries()) {
            const original = paths[index].points;
            const points = routed.points;
            const last = points.length - 1;
            expect(points[0]).toEqual(original[0]);
            expect(points[last]).toEqual(original[last]);
            expect(points[1].y).toBe(points[0].y);
            expect(points[last - 1].y).toBe(points[last].y);
            expect(points[1].x - points[0].x).toBeGreaterThanOrEqual(20);
            expect(points[last].x - points[last - 1].x).toBeGreaterThanOrEqual(20);
        }
    });

    it('separates two return legs sharing the gap between stacked nodes', () => {
        // Padded boxes 75 and 105 leave a 30-px gap; both legs run on its midline (90).
        const stacked: Rect[] = [
            { left: -15, top: -15, right: 345, bottom: 75 },
            { left: -15, top: 105, right: 345, bottom: 195 },
        ];
        const paths = [
            path('a', [
                { x: 335, y: 30 },
                { x: 355, y: 30 },
                { x: 355, y: 90 },
                { x: -45, y: 90 },
                { x: -45, y: 170 },
                { x: -5, y: 170 },
            ]),
            path('b', [
                { x: 335, y: 10 },
                { x: 375, y: 10 },
                { x: 375, y: 90 },
                { x: -25, y: 90 },
                { x: -25, y: 150 },
                { x: -5, y: 150 },
            ]),
        ];

        expect(report(paths)).toEqual({ crossings: 0, collinearOverlaps: 1 });

        const nudged = nudgePaths(paths, stacked);

        const legs = nudged.map((routed) => routed.points[2].y);
        expect(legs.every((y) => y >= 75 && y <= 105)).toBe(true);
        expect(Math.abs(legs[0] - legs[1])).toBeGreaterThanOrEqual(10);
        expect(report(nudged)).toEqual({ crossings: 0, collinearOverlaps: 0 });
    });

    it('nests the risers of stacked sources returning up, the lowest outermost (flow 6)', () => {
        // Py#4 (y 450) and Py#6 (y 570) return into one table input, Py#5 (y 510) over the top of
        // everything; the router leaves all three risers on x 3155. A trunk riser for Py#4 + Py#6
        // would be crossed by Py#5's stub; nested, only Py#6's leg crosses Py#5's riser (the one
        // crossing the three can't avoid: Py#5's port sits between two wires into one port).
        const returning = (
            id: string,
            portY: number,
            legY: number,
            target: IPoint,
            targetPortKey: string
        ): RoutedPath =>
            path(
                id,
                [
                    { x: 3135, y: portY },
                    { x: 3155, y: portY },
                    { x: 3155, y: legY },
                    { x: target.x - 20, y: legY },
                    { x: target.x - 20, y: target.y },
                    target,
                ],
                `${id}_out`,
                targetPortKey
            );
        const paths = [
            returning('py4', 450, 345, { x: 2173, y: 390 }, 'dt10_in'),
            returning('py5', 510, 85, { x: 435, y: 210 }, 'py7_in'),
            returning('py6', 570, 345, { x: 2173, y: 390 }, 'dt10_in'),
        ];

        const [py4, py5, py6] = nudgePaths(paths, []);

        const [x4, x5, x6] = [py4, py5, py6].map((routed) => routed.points[1].x);
        expect(x4).toBeLessThan(x5);
        expect(x5).toBeLessThan(x6);
        expect(report([py4, py5, py6])).toEqual({ crossings: 1, collinearOverlaps: 0 });
    });

    it('never stretches a leg onto another wire’s last segment when separating a riser', () => {
        // Seed 227 (scattered): b's riser overlaps c's; moving b right would stretch b's leg (y 410,
        // leftwards) onto a's last segment (y 410, x 1745..1795), which never moves.
        const paths = [
            path('a', [
                { x: 1370, y: 490 },
                { x: 1745, y: 490 },
                { x: 1745, y: 410 },
                { x: 1795, y: 410 },
            ]),
            path('b', [
                { x: 2000, y: 0 },
                { x: 2020, y: 0 },
                { x: 2020, y: 45 },
                { x: 1745, y: 45 },
                { x: 1745, y: 410 },
                { x: 395, y: 410 },
                { x: 395, y: 500 },
                { x: 415, y: 500 },
            ]),
            path('c', [
                { x: 1500, y: 20 },
                { x: 1520, y: 20 },
                { x: 1520, y: 35 },
                { x: 1745, y: 35 },
                { x: 1745, y: 70 },
                { x: 1900, y: 70 },
                { x: 1900, y: 90 },
                { x: 1920, y: 90 },
            ]),
        ];
        expect(report(paths).collinearOverlaps).toBe(1);

        expect(report(nudgePaths(paths, [])).collinearOverlaps).toBe(0);
    });

    it('is deterministic', () => {
        const paths = [0, 1, 2].map((index) =>
            path(`w${index}`, [
                { x: 335, y: 30 + index * 100 },
                { x: 560, y: 30 + index * 100 },
                { x: 560, y: 330 + index * 100 },
                { x: 795, y: 330 + index * 100 },
            ])
        );

        expect(nudgePaths(paths, [])).toEqual(nudgePaths(paths, []));
    });
});
