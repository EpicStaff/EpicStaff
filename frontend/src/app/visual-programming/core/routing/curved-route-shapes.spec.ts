import { IPoint } from '@foblex/2d';

import { buildCatmullRomPath, computeBackwardControlPoints, computeForwardControlPoints } from './curved-route-shapes';
import { Rect, WIRE_CLEARANCE } from './obstacles';

describe('buildCatmullRomPath', () => {
    it('returns empty string for fewer than 2 points', () => {
        expect(buildCatmullRomPath([])).toBe('');
        expect(buildCatmullRomPath([{ x: 0, y: 0 }])).toBe('');
    });

    it('returns a path with M and C commands for 2 points, no L commands', () => {
        const source: IPoint = { x: 0, y: 0 };
        const target: IPoint = { x: 200, y: 100 };

        const path = buildCatmullRomPath([source, target]);

        expect(path).toMatch(/^M 0 0/);
        expect(path).toContain('C');
        expect(path).not.toMatch(/\bL\b/);
    });

    it('returns a smooth path with multiple C segments for 3+ points', () => {
        const points: IPoint[] = [
            { x: 0, y: 0 },
            { x: 100, y: 50 },
            { x: 200, y: 0 },
            { x: 300, y: 50 },
        ];

        const path = buildCatmullRomPath(points);

        expect(path).toMatch(/^M 0 0/);
        // 3 segments for 4 points
        const cCount = (path.match(/C /g) ?? []).length;
        expect(cCount).toBe(3);
        expect(path).not.toMatch(/\bL\b/);
    });

    it('starts with M {source.x} {source.y}', () => {
        const source: IPoint = { x: 42, y: 73 };
        const target: IPoint = { x: 300, y: 200 };

        const path = buildCatmullRomPath([source, target]);

        expect(path).toMatch(/^M 42 73/);
    });

    it('ends at the last point', () => {
        const points: IPoint[] = [
            { x: 0, y: 0 },
            { x: 100, y: 50 },
            { x: 250, y: 80 },
        ];

        const path = buildCatmullRomPath(points);

        expect(path).toMatch(/250 80$/);
    });
});

describe('computeForwardControlPoints', () => {
    it('returns exactly 2 points', () => {
        const result = computeForwardControlPoints({ x: 0, y: 0 }, { x: 400, y: 100 });

        expect(result).toHaveLength(2);
    });

    it('first point exits east (x > source.x)', () => {
        const source: IPoint = { x: 100, y: 50 };
        const target: IPoint = { x: 500, y: 200 };

        const [first] = computeForwardControlPoints(source, target);

        expect(first.x).toBeGreaterThan(source.x);
    });

    it('second point enters west (x < target.x)', () => {
        const source: IPoint = { x: 100, y: 50 };
        const target: IPoint = { x: 500, y: 200 };

        const [, second] = computeForwardControlPoints(source, target);

        expect(second.x).toBeLessThan(target.x);
    });

    it('blends y values between source and target', () => {
        const source: IPoint = { x: 0, y: 0 };
        const target: IPoint = { x: 400, y: 100 };

        const [first, second] = computeForwardControlPoints(source, target);

        // Through-points blend Y at 25% and 75% to avoid overshoot
        expect(first.y).toBe(25);
        expect(second.y).toBe(75);
    });

    it('caps offset at half the horizontal distance for close points', () => {
        const source: IPoint = { x: 0, y: 0 };
        const target: IPoint = { x: 10, y: 0 };

        const [first, second] = computeForwardControlPoints(source, target);

        // offset = min(10 * 0.4, 10 / 2, 200) = 4
        expect(first.x).toBe(source.x + 4);
        expect(second.x).toBe(target.x - 4);
        // Through-points never cross
        expect(first.x).toBeLessThanOrEqual(second.x);
    });

    it('clamps offset for very far apart points (maximum 200)', () => {
        const source: IPoint = { x: 0, y: 0 };
        const target: IPoint = { x: 2000, y: 0 };

        const [first, second] = computeForwardControlPoints(source, target);

        // offset = clamp(2000 * 0.4, 50, 200) = 200
        expect(first.x).toBe(source.x + 200);
        expect(second.x).toBe(target.x - 200);
    });
});

describe('computeBackwardControlPoints', () => {
    const source: IPoint = { x: 500, y: 100 };
    const target: IPoint = { x: 100, y: 200 };

    it('returns exactly 4 points', () => {
        const result = computeBackwardControlPoints(source, target, null, null);

        expect(result).toHaveLength(4);
    });

    it('exit stub x > source.x and entry stub x < target.x', () => {
        const [exitStub, , , entryStub] = computeBackwardControlPoints(source, target, null, null);

        expect(exitStub.x).toBeGreaterThan(source.x);
        expect(entryStub.x).toBeLessThan(target.x);
    });

    it('loop goes above both points when obstacles are null', () => {
        const [, topRight, topLeft] = computeBackwardControlPoints(source, target, null, null);

        // DEFAULT_VERTICAL_CLEARANCE = WIRE_CLEARANCE * 4 = 40
        // sourceTop = source.y - 40 = 60, targetTop = target.y - 40 = 160
        // clearanceY = min(60, 160) - 40 = 20
        expect(topRight.y).toBeLessThan(source.y);
        expect(topLeft.y).toBeLessThan(target.y);
        expect(topRight.y).toBe(topLeft.y);
    });

    it('loop clears the obstacle rects when provided', () => {
        const sourceObstacle: Rect = { left: 480, top: 50, right: 620, bottom: 150 };
        const targetObstacle: Rect = { left: 80, top: 80, right: 220, bottom: 250 };

        const [, topRight, topLeft] = computeBackwardControlPoints(source, target, sourceObstacle, targetObstacle);

        expect(topRight.y).toBeLessThan(sourceObstacle.top);
        expect(topLeft.y).toBeLessThan(targetObstacle.top);
    });

    it('uses fallback clearance from port positions when obstacles are null', () => {
        const defaultVerticalClearance = WIRE_CLEARANCE * 4;
        const [, topRight] = computeBackwardControlPoints(source, target, null, null);

        // Without obstacles: sourceTop = source.y - defaultVerticalClearance
        // clearanceY = min(sourceTop, targetTop) - defaultVerticalClearance
        const expectedSourceTop = source.y - defaultVerticalClearance;
        const expectedTargetTop = target.y - defaultVerticalClearance;
        const expectedClearanceY = Math.min(expectedSourceTop, expectedTargetTop) - defaultVerticalClearance;

        expect(topRight.y).toBe(expectedClearanceY);
    });
});
