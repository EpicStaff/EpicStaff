import { IPoint } from '@foblex/2d';

import {
    onSegment,
    orientation,
    pointInsideRect,
    segmentIntersectsRect,
    SegmentRect,
    segmentsIntersect,
} from './segment-math';

describe('orientation', () => {
    it.each([
        [{ x: 0, y: 0 }, { x: 1, y: 1 }, { x: 2, y: 2 }, 0],
        [{ x: 0, y: 0 }, { x: 1, y: 0 }, { x: 2, y: 0 }, 0],
        [{ x: 0, y: 0 }, { x: 1, y: 1 }, { x: 2, y: 0 }, 1],
        [{ x: 0, y: 0 }, { x: 1, y: 1 }, { x: 0, y: 2 }, 2],
    ] satisfies [IPoint, IPoint, IPoint, number][])(
        'returns %d for points %o, %o, %o',
        (a: IPoint, b: IPoint, c: IPoint, expected: number) => {
            expect(orientation(a, b, c)).toBe(expected);
        }
    );
});

describe('onSegment', () => {
    it('returns true when the point lies on the segment', () => {
        expect(onSegment({ x: 0, y: 0 }, { x: 1, y: 1 }, { x: 2, y: 2 })).toBe(true);
    });

    it('returns true for an endpoint', () => {
        expect(onSegment({ x: 0, y: 0 }, { x: 0, y: 0 }, { x: 2, y: 2 })).toBe(true);
    });

    it('returns false when the point is outside the segment', () => {
        expect(onSegment({ x: 0, y: 0 }, { x: 3, y: 3 }, { x: 2, y: 2 })).toBe(false);
    });

    it('returns false when the point is off the line in the other direction', () => {
        expect(onSegment({ x: 0, y: 0 }, { x: -1, y: -1 }, { x: 2, y: 2 })).toBe(false);
    });
});

describe('segmentsIntersect', () => {
    it('detects crossing segments', () => {
        expect(segmentsIntersect({ x: 0, y: 0 }, { x: 10, y: 10 }, { x: 10, y: 0 }, { x: 0, y: 10 })).toBe(true);
    });

    it('returns false for parallel non-overlapping segments', () => {
        expect(segmentsIntersect({ x: 0, y: 0 }, { x: 10, y: 0 }, { x: 0, y: 5 }, { x: 10, y: 5 })).toBe(false);
    });

    it('detects collinear overlapping segments', () => {
        expect(segmentsIntersect({ x: 0, y: 0 }, { x: 5, y: 0 }, { x: 3, y: 0 }, { x: 8, y: 0 })).toBe(true);
    });

    it('returns false for collinear non-overlapping segments', () => {
        expect(segmentsIntersect({ x: 0, y: 0 }, { x: 3, y: 0 }, { x: 5, y: 0 }, { x: 8, y: 0 })).toBe(false);
    });

    it('detects a T-junction (endpoint on segment)', () => {
        expect(segmentsIntersect({ x: 0, y: 0 }, { x: 10, y: 0 }, { x: 5, y: -5 }, { x: 5, y: 0 })).toBe(true);
    });

    it('detects a shared endpoint', () => {
        expect(segmentsIntersect({ x: 0, y: 0 }, { x: 5, y: 5 }, { x: 5, y: 5 }, { x: 10, y: 0 })).toBe(true);
    });

    it('returns false for segments that do not touch', () => {
        expect(segmentsIntersect({ x: 0, y: 0 }, { x: 1, y: 0 }, { x: 5, y: 5 }, { x: 6, y: 6 })).toBe(false);
    });
});

describe('pointInsideRect', () => {
    const rect: SegmentRect = { x: 0, y: 0, width: 10, height: 10 };

    it('returns true for a point inside the rectangle', () => {
        expect(pointInsideRect({ x: 5, y: 5 }, rect)).toBe(true);
    });

    it('returns true for a point on the edge', () => {
        expect(pointInsideRect({ x: 0, y: 5 }, rect)).toBe(true);
        expect(pointInsideRect({ x: 10, y: 10 }, rect)).toBe(true);
    });

    it('returns false for a point outside the rectangle', () => {
        expect(pointInsideRect({ x: -1, y: 5 }, rect)).toBe(false);
        expect(pointInsideRect({ x: 11, y: 5 }, rect)).toBe(false);
        expect(pointInsideRect({ x: 5, y: -1 }, rect)).toBe(false);
        expect(pointInsideRect({ x: 5, y: 11 }, rect)).toBe(false);
    });
});

describe('segmentIntersectsRect', () => {
    const rect: SegmentRect = { x: 0, y: 0, width: 10, height: 10 };

    it('returns true when a segment crosses the rectangle', () => {
        expect(segmentIntersectsRect({ x: -5, y: 5 }, { x: 15, y: 5 }, rect)).toBe(true);
    });

    it('returns true when one endpoint is inside the rectangle', () => {
        expect(segmentIntersectsRect({ x: 5, y: 5 }, { x: 20, y: 20 }, rect)).toBe(true);
    });

    it('returns true when both endpoints are inside the rectangle', () => {
        expect(segmentIntersectsRect({ x: 2, y: 2 }, { x: 8, y: 8 }, rect)).toBe(true);
    });

    it('returns false when the segment is entirely outside the rectangle', () => {
        expect(segmentIntersectsRect({ x: 20, y: 20 }, { x: 30, y: 30 }, rect)).toBe(false);
    });

    it('returns true when the segment touches a corner', () => {
        expect(segmentIntersectsRect({ x: -5, y: -5 }, { x: 0, y: 0 }, rect)).toBe(true);
    });

    it('returns false for a segment that passes near but does not touch', () => {
        expect(segmentIntersectsRect({ x: -5, y: -1 }, { x: 15, y: -1 }, rect)).toBe(false);
    });
});
