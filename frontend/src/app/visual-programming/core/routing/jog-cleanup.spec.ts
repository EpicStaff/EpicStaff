import { IPoint } from '@foblex/2d';

import { measure } from '../layout/quality/metrics';
import { removeJogs } from './jog-cleanup';
import { RoutedPath } from './nudging';
import { Rect } from './obstacles';

function path(id: string, points: IPoint[]): RoutedPath {
    return { id, sourcePortKey: `${id}_out`, targetPortKey: `${id}_in`, points };
}

function report(paths: RoutedPath[]): { shortSegments: number; crossings: number; collinearOverlaps: number } {
    const wires = paths.map((routed) => ({
        ...routed,
        sourceNodeId: `${routed.id}-s`,
        targetNodeId: `${routed.id}-t`,
    }));
    const { shortSegments, crossings, collinearOverlaps } = measure([], wires);
    return { shortSegments, crossings, collinearOverlaps };
}

// A wire that runs right, down, jogs 4 px right, down again and right into its target.
const JOGGED = [
    { x: 335, y: 30 },
    { x: 560, y: 30 },
    { x: 560, y: 180 },
    { x: 564, y: 180 },
    { x: 564, y: 330 },
    { x: 795, y: 330 },
];

describe('removeJogs', () => {
    it('aligns the two risers around a 4-px jog into one', () => {
        const [cleaned] = removeJogs([path('w', JOGGED)], []);

        expect(cleaned.points).toEqual([
            { x: 335, y: 30 },
            { x: 564, y: 30 },
            { x: 564, y: 330 },
            { x: 795, y: 330 },
        ]);
        expect(report([cleaned]).shortSegments).toBe(0);
    });

    it('takes the other side when the first one would enter a node', () => {
        // A node's padded box starts at x 562: the upper riser can't move to 564, so the lower one moves to 560.
        const obstacle: Rect = { left: 562, top: 60, right: 700, bottom: 150 };

        const [cleaned] = removeJogs([path('w', JOGGED)], [obstacle]);

        expect(cleaned.points).toEqual([
            { x: 335, y: 30 },
            { x: 560, y: 30 },
            { x: 560, y: 330 },
            { x: 795, y: 330 },
        ]);
    });

    it('keeps a jog when every way out would add a crossing', () => {
        // Wires ending or starting just beside both risers, at 557/562 above the jog and 562/567
        // below it: aligning either riser (to 564 or 560) or widening the jog (to 554 or 570)
        // would cross one of them.
        const others = [
            path('above', [
                { x: 562, y: 100 },
                { x: 900, y: 100 },
            ]),
            path('aboveLeft', [
                { x: 100, y: 100 },
                { x: 557, y: 100 },
            ]),
            path('below', [
                { x: 100, y: 250 },
                { x: 562, y: 250 },
            ]),
            path('belowRight', [
                { x: 567, y: 250 },
                { x: 900, y: 250 },
            ]),
        ];

        const [cleaned] = removeJogs([path('w', JOGGED), ...others], []);

        expect(cleaned.points).toEqual(JOGGED);
    });

    it('widens a jog next to a stub to 10 px when aligning would double the wire back', () => {
        // The wire runs up past its target's row, 2 px right and 10 px down into the last stub:
        // aligning would fold it back on itself, so the rising segment moves 8 px left instead.
        const points = [
            { x: 1950, y: 490 },
            { x: 1970, y: 490 },
            { x: 1970, y: 430 },
            { x: 613, y: 430 },
            { x: 613, y: 210 },
            { x: 615, y: 210 },
            { x: 615, y: 220 },
            { x: 635, y: 220 },
        ];

        const [cleaned] = removeJogs([path('w', points)], []);

        expect(cleaned.points).toEqual([
            { x: 1950, y: 490 },
            { x: 1970, y: 490 },
            { x: 1970, y: 430 },
            { x: 605, y: 430 },
            { x: 605, y: 210 },
            { x: 615, y: 210 },
            { x: 615, y: 220 },
            { x: 635, y: 220 },
        ]);
        expect(report([cleaned]).shortSegments).toBe(0);
    });

    it('never moves a stub: a jog between the two stubs of ports 4 px apart stays', () => {
        const points = [
            { x: 335, y: 30 },
            { x: 560, y: 30 },
            { x: 560, y: 34 },
            { x: 795, y: 34 },
        ];

        const [cleaned] = removeJogs([path('w', points)], []);

        expect(cleaned.points).toEqual(points);
    });

    it('leaves the other paths and the order alone', () => {
        const other = path('other', [
            { x: 0, y: 500 },
            { x: 900, y: 500 },
        ]);

        const cleaned = removeJogs([path('w', JOGGED), other], []);

        expect(cleaned.map((routed) => routed.id)).toEqual(['w', 'other']);
        expect(cleaned[1]).toEqual(other);
    });
});
