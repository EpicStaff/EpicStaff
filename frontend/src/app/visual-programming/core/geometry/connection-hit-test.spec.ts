import { IPoint } from '@foblex/2d';

import { polylineIntersectsRect, Rect } from './connection-hit-test';

describe('polylineIntersectsRect', () => {
    const rect: Rect = { x: 100, y: 100, width: 200, height: 60 };

    it('returns false for an empty path', () => {
        expect(polylineIntersectsRect([], rect)).toBe(false);
    });

    it('returns false for a single point (no segments)', () => {
        expect(polylineIntersectsRect([{ x: 150, y: 130 }], rect)).toBe(false);
    });

    it('returns true when a segment crosses the rect horizontally', () => {
        const path: IPoint[] = [
            { x: 0, y: 130 },
            { x: 400, y: 130 },
        ];
        expect(polylineIntersectsRect(path, rect)).toBe(true);
    });

    it('returns true when a segment starts inside the rect', () => {
        const path: IPoint[] = [
            { x: 150, y: 120 },
            { x: 500, y: 120 },
        ];
        expect(polylineIntersectsRect(path, rect)).toBe(true);
    });

    it('returns true when a segment ends inside the rect', () => {
        const path: IPoint[] = [
            { x: 0, y: 130 },
            { x: 200, y: 130 },
        ];
        expect(polylineIntersectsRect(path, rect)).toBe(true);
    });

    it('returns false when the segment is entirely above the rect', () => {
        const path: IPoint[] = [
            { x: 0, y: 50 },
            { x: 400, y: 50 },
        ];
        expect(polylineIntersectsRect(path, rect)).toBe(false);
    });

    it('returns false when the segment is entirely to the right', () => {
        const path: IPoint[] = [
            { x: 350, y: 0 },
            { x: 350, y: 300 },
        ];
        expect(polylineIntersectsRect(path, rect)).toBe(false);
    });

    it('returns true when only the second segment of a polyline crosses', () => {
        const path: IPoint[] = [
            { x: 0, y: 50 },
            { x: 50, y: 50 },
            { x: 50, y: 130 },
            { x: 200, y: 130 },
        ];
        expect(polylineIntersectsRect(path, rect)).toBe(true);
    });

    it('returns true when a segment is entirely inside the rect', () => {
        const path: IPoint[] = [
            { x: 150, y: 120 },
            { x: 250, y: 140 },
        ];
        expect(polylineIntersectsRect(path, rect)).toBe(true);
    });

    it('returns true for a diagonal segment crossing the rect corner', () => {
        const path: IPoint[] = [
            { x: 50, y: 50 },
            { x: 200, y: 200 },
        ];
        expect(polylineIntersectsRect(path, rect)).toBe(true);
    });
});
