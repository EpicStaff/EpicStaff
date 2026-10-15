import { Rect } from './obstacles';

/**
 * A sparse orthogonal routing grid. The lines are the obstacle edges, the midpoints
 * between consecutive edges (channel centres, e.g. the midline of the gap between stacked nodes) and the caller's extras
 * (port and stub coordinates). A point or a step between neighbouring lines is blocked when it
 * lies strictly inside an obstacle; the edges themselves stay free. Every obstacle edge is a grid
 * line, so testing a step's midpoint is exact. Steps along an edge are flagged too, so the search
 * can prefer channel centres to hugging a node's padding, and so are steps squeezed between two
 * edges (two padded boxes touching, e.g. nodes stacked 20 px apart): a corridor of zero width, where
 * nudging has no room to put a second wire beside the first.
 */
export interface RoutingGrid {
    readonly xs: readonly number[]; // sorted, unique
    readonly ys: readonly number[]; // sorted, unique
    indexOfX(x: number): number; // -1 if absent
    indexOfY(y: number): number; // -1 if absent
    isPointBlocked(xi: number, yi: number): boolean;
    isHorizontalStepBlocked(xi: number, yi: number): boolean; // xs[xi] → xs[xi+1] at ys[yi]
    isVerticalStepBlocked(xi: number, yi: number): boolean; // ys[yi] → ys[yi+1] at xs[xi]
    isHorizontalStepOnObstacleEdge(xi: number, yi: number): boolean;
    isVerticalStepOnObstacleEdge(xi: number, yi: number): boolean;
    // The raw flags behind the methods above (index = yi × xs.length + xi), for the search's hot loop.
    readonly pointBlocked: Uint8Array; // 1 = strictly inside an obstacle
    readonly horizontalSteps: Uint8Array; // STEP_BLOCKED | STEP_ON_EDGE | STEP_SQUEEZED bits
    readonly verticalSteps: Uint8Array;
}

// Step flags: bit 0 = strictly inside an obstacle, bit 1 = along an obstacle's edge, bits 2 and 3 =
// along the edge of an obstacle on the lower / higher coordinate side; both of them: squeezed.
export const STEP_BLOCKED = 1;
export const STEP_ON_EDGE = 2;
const OBSTACLE_BEFORE = 4;
const OBSTACLE_AFTER = 8;
export const STEP_SQUEEZED = OBSTACLE_BEFORE | OBSTACLE_AFTER;
const BLOCKED = STEP_BLOCKED;
const ON_EDGE = STEP_ON_EDGE;

export function buildRoutingGrid(obstacles: Rect[], extraXs: number[], extraYs: number[]): RoutingGrid {
    const xs = gridLines(
        obstacles.flatMap((obstacle) => [obstacle.left, obstacle.right]),
        extraXs
    );
    const ys = gridLines(
        obstacles.flatMap((obstacle) => [obstacle.top, obstacle.bottom]),
        extraYs
    );
    const columns = xs.length;
    const pointBlocked = new Uint8Array(columns * ys.length);
    const horizontalSteps = new Uint8Array(columns * ys.length);
    const verticalSteps = new Uint8Array(columns * ys.length);

    for (const obstacle of obstacles) {
        // Lines strictly inside the obstacle, and the lines of its own edges.
        const innerXFirst = firstIndexAbove(xs, obstacle.left);
        const innerXLast = firstIndexAtOrAbove(xs, obstacle.right) - 1;
        const innerYFirst = firstIndexAbove(ys, obstacle.top);
        const innerYLast = firstIndexAtOrAbove(ys, obstacle.bottom) - 1;
        const edgeXFirst = firstIndexAtOrAbove(xs, obstacle.left);
        const edgeXLast = innerXLast + 1;
        const edgeYFirst = firstIndexAtOrAbove(ys, obstacle.top);
        const edgeYLast = innerYLast + 1;
        for (let yi = innerYFirst; yi <= innerYLast; yi++) {
            const row = yi * columns;
            for (let xi = innerXFirst; xi <= innerXLast; xi++) pointBlocked[row + xi] = 1;
            for (let xi = edgeXFirst; xi < edgeXLast; xi++) horizontalSteps[row + xi] |= BLOCKED;
        }
        for (let yi = edgeYFirst; yi < edgeYLast; yi++) {
            const row = yi * columns;
            for (let xi = innerXFirst; xi <= innerXLast; xi++) verticalSteps[row + xi] |= BLOCKED;
            verticalSteps[row + edgeXFirst] |= ON_EDGE | OBSTACLE_AFTER;
            verticalSteps[row + edgeXLast] |= ON_EDGE | OBSTACLE_BEFORE;
        }
        for (let xi = edgeXFirst; xi < edgeXLast; xi++) {
            horizontalSteps[edgeYFirst * columns + xi] |= ON_EDGE | OBSTACLE_AFTER;
            horizontalSteps[edgeYLast * columns + xi] |= ON_EDGE | OBSTACLE_BEFORE;
        }
    }

    return {
        xs,
        ys,
        indexOfX: (x) => indexOf(xs, x),
        indexOfY: (y) => indexOf(ys, y),
        isPointBlocked: (xi, yi) => pointBlocked[yi * columns + xi] === 1,
        isHorizontalStepBlocked: (xi, yi) => (horizontalSteps[yi * columns + xi] & BLOCKED) !== 0,
        isVerticalStepBlocked: (xi, yi) => (verticalSteps[yi * columns + xi] & BLOCKED) !== 0,
        isHorizontalStepOnObstacleEdge: (xi, yi) => (horizontalSteps[yi * columns + xi] & ON_EDGE) !== 0,
        isVerticalStepOnObstacleEdge: (xi, yi) => (verticalSteps[yi * columns + xi] & ON_EDGE) !== 0,
        pointBlocked,
        horizontalSteps,
        verticalSteps,
    };
}

// Edges, the midpoint between each consecutive pair of distinct edges, and the extras; sorted, unique.
function gridLines(edges: number[], extras: number[]): number[] {
    const sortedEdges = uniqueSorted(edges);
    const midpoints = sortedEdges.slice(1).map((edge, index) => (sortedEdges[index] + edge) / 2);
    return uniqueSorted([...sortedEdges, ...midpoints, ...extras]);
}

function uniqueSorted(values: number[]): number[] {
    return [...new Set(values)].sort((first, second) => first - second);
}

/** Index of the first value ≥ target in a sorted array (its length when none). */
export function firstIndexAtOrAbove(values: readonly number[], target: number): number {
    let low = 0;
    let high = values.length;
    while (low < high) {
        const middle = (low + high) >> 1;
        if (values[middle] < target) low = middle + 1;
        else high = middle;
    }
    return low;
}

/** Index of the first value > target in a sorted array (its length when none). */
export function firstIndexAbove(values: readonly number[], target: number): number {
    let low = 0;
    let high = values.length;
    while (low < high) {
        const middle = (low + high) >> 1;
        if (values[middle] <= target) low = middle + 1;
        else high = middle;
    }
    return low;
}

function indexOf(values: readonly number[], target: number): number {
    const index = firstIndexAtOrAbove(values, target);
    return values[index] === target ? index : -1;
}
