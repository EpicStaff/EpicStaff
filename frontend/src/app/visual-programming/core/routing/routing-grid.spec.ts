import { buildRoutingGrid, STEP_SQUEEZED } from './routing-grid';

describe('routing grid', () => {
    it('adds obstacle edges, extras and midpoints, and blocks only the interior', () => {
        const grid = buildRoutingGrid([{ left: 0, top: 0, right: 100, bottom: 100 }], [-40, 160], [50, 130]);

        expect(grid.xs).toEqual([-40, 0, 50, 100, 160]);
        expect(grid.ys).toEqual([0, 50, 100, 130]);

        const x0 = grid.indexOfX(0);
        const x50 = grid.indexOfX(50);
        const y50 = grid.indexOfY(50);
        expect(grid.isPointBlocked(x50, y50)).toBe(true);
        expect(grid.isPointBlocked(x0, y50)).toBe(false); // on the edge
        expect(grid.isHorizontalStepBlocked(x0, y50)).toBe(true); // 0 → 50 across the interior
        expect(grid.isHorizontalStepBlocked(grid.indexOfX(-40), y50)).toBe(false); // -40 → 0, outside
        expect(grid.isHorizontalStepBlocked(x0, grid.indexOfY(0))).toBe(false); // along the top edge
        expect(grid.isVerticalStepBlocked(x0, grid.indexOfY(0))).toBe(false); // along the left edge
        expect(grid.isVerticalStepBlocked(x50, grid.indexOfY(0))).toBe(true);
    });

    it('flags steps that run along an obstacle edge', () => {
        const grid = buildRoutingGrid([{ left: 0, top: 0, right: 100, bottom: 100 }], [-40, 160], [50, 130]);
        const x0 = grid.indexOfX(0);
        const y0 = grid.indexOfY(0);

        expect(grid.isHorizontalStepOnObstacleEdge(x0, y0)).toBe(true); // along the top edge
        expect(grid.isHorizontalStepOnObstacleEdge(x0, grid.indexOfY(100))).toBe(true); // along the bottom edge
        expect(grid.isVerticalStepOnObstacleEdge(x0, y0)).toBe(true); // along the left edge
        expect(grid.isHorizontalStepOnObstacleEdge(grid.indexOfX(-40), y0)).toBe(false); // on the edge's line, beyond it
        expect(grid.isVerticalStepOnObstacleEdge(grid.indexOfX(-40), y0)).toBe(false);
        expect(grid.isHorizontalStepOnObstacleEdge(x0, grid.indexOfY(130))).toBe(false);
    });

    it('flags steps squeezed between two touching padded boxes, not those along one edge', () => {
        // Two nodes stacked 20 px apart: their boxes, padded by 10, touch on y 100.
        const grid = buildRoutingGrid(
            [
                { left: 0, top: 0, right: 100, bottom: 100 },
                { left: 0, top: 100, right: 100, bottom: 200 },
                { left: 0, top: 300, right: 100, bottom: 400 },
            ],
            [],
            []
        );
        const squeezed = (flags: number): boolean => (flags & STEP_SQUEEZED) === STEP_SQUEEZED;
        const step = (xi: number, yi: number): number => grid.horizontalSteps[yi * grid.xs.length + xi];

        expect(squeezed(step(grid.indexOfX(0), grid.indexOfY(100)))).toBe(true);
        expect(squeezed(step(grid.indexOfX(0), grid.indexOfY(200)))).toBe(false); // open below
        expect(squeezed(step(grid.indexOfX(0), grid.indexOfY(300)))).toBe(false); // open above
    });

    it('returns -1 for a coordinate that is not a grid line', () => {
        const grid = buildRoutingGrid([{ left: 0, top: 0, right: 100, bottom: 100 }], [], []);

        expect(grid.indexOfX(25)).toBe(-1);
        expect(grid.indexOfY(-1)).toBe(-1);
    });

    it('puts the midline of a 60-px gap between two stacked obstacles on the grid', () => {
        const grid = buildRoutingGrid(
            [
                { left: 0, top: 0, right: 100, bottom: 100 },
                { left: 0, top: 160, right: 100, bottom: 260 },
            ],
            [],
            []
        );

        const midline = grid.indexOfY(130);
        expect(midline).toBeGreaterThanOrEqual(0);
        expect(grid.isHorizontalStepBlocked(grid.indexOfX(0), midline)).toBe(false);
    });

    it('works with negative and very large coordinates', () => {
        const grid = buildRoutingGrid(
            [
                { left: -3015, top: 49985, right: -2655, bottom: 50075 },
                { left: -3015, top: -15, right: -2655, bottom: 75 },
            ],
            [-3040],
            [50030]
        );

        expect(grid.xs).toEqual([-3040, -3015, -2835, -2655]);
        expect(grid.ys).toEqual([-15, 30, 75, 25030, 49985, 50030, 50075]);
        expect(grid.isPointBlocked(grid.indexOfX(-2835), grid.indexOfY(50030))).toBe(true);
        expect(grid.isPointBlocked(grid.indexOfX(-2835), grid.indexOfY(25030))).toBe(false);
        expect(grid.isVerticalStepBlocked(grid.indexOfX(-3040), grid.indexOfY(75))).toBe(false);
    });
});
