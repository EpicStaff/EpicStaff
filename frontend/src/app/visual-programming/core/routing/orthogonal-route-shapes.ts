import { IPoint } from '@foblex/2d';

/**
 * Shapes shared by the orthogonal builder and the router's no-route fallback. Pure
 * functions over full point lists, port to port.
 */

const STUB = 20;
// Foblex's port points come from DOM rects and can be a pixel or two off getPortPosition.
const SNAP_TOLERANCE = 3;
// Below this vertical distance between the ports the fallback assumes the two nodes' boxes
// overlap vertically, so there is no gap to return through (the builder doesn't know the boxes;
// 60 px is the height of the smallest node, whose port sits at its centre).
const MIN_RETURN_GAP = 60;
// ...and then it drops this far below the lower port: 40 px under a 60-px node.
const RETURN_DROP = 70;

/** An SVG path through the points with rounded corners (radius capped at half of each leg). */
export function buildRoundedOrthogonalPath(points: IPoint[], radius: number): string {
    let path = '';

    for (let index = 0; index < points.length; index++) {
        const point = points[index];

        if (index === 0) {
            path += `M ${point.x} ${point.y}`;
        } else if (index === points.length - 1) {
            path += `L ${point.x + 0.0002} ${point.y + 0.0002}`;
        } else {
            path += getBend(points[index - 1], point, points[index + 1], radius);
        }
    }

    return path;
}

/**
 * Full points `[source, ...waypoints, target]` made orthogonal: the first and last waypoints are
 * snapped onto the port rows when within 3 px, and each pair that differs in both axes gets an
 * elbow. The wire leaves the source and enters the target horizontally; in between, an elbow's
 * first leg continues the previous leg's axis, so consecutive elbows alternate.
 */
export function orthogonalize(source: IPoint, waypoints: IPoint[], target: IPoint): IPoint[] {
    return orthogonalStretches(source, waypoints, target).flatMap((stretch, index) =>
        index === 0 ? stretch : stretch.slice(1)
    );
}

/**
 * `orthogonalize`, split per anchor pair: stretch i runs from anchor i to anchor i + 1 of
 * `[source, ...waypoints, target]`, elbow included. The builder puts one waypoint candidate on each.
 */
export function orthogonalStretches(source: IPoint, waypoints: IPoint[], target: IPoint): IPoint[][] {
    const anchors = snappedAnchors(source, waypoints, target);
    const last = anchors.length - 1;
    const stretches: IPoint[][] = [];
    let previousLegHorizontal = true;
    for (let index = 0; index < last; index++) {
        const from = anchors[index];
        const to = anchors[index + 1];
        if (from.x === to.x || from.y === to.y) {
            stretches.push([from, to]);
            if (from.x !== to.x || from.y !== to.y) previousLegHorizontal = from.y === to.y;
            continue;
        }
        const horizontalFirst: boolean = index === last - 1 && index > 0 ? false : previousLegHorizontal;
        const elbow = horizontalFirst ? { x: to.x, y: from.y } : { x: from.x, y: to.y };
        stretches.push([from, elbow, to]);
        previousLegHorizontal = !horizontalFirst;
    }
    return stretches;
}

/**
 * The interior points a waypoint edit stands for, orthogonal and without redundant
 * points; on the router's own output it is the identity. Foblex edits one point at a time: a
 * dragged candidate (or bend) sits off the line through its two neighbours, and that means "move
 * this stretch": off a vertical, the riser moves to the point's x; off a horizontal, the leg moves
 * to its y, keeping the port stubs. Then elbows, redundant points and too-short stubs.
 */
export function normalizeOrthogonalWaypoints(source: IPoint, waypoints: IPoint[], target: IPoint): IPoint[] {
    const moved = moveDraggedStretches(snappedAnchors(source, waypoints, target));
    const orthogonal = removeRedundantPoints(orthogonalize(source, moved.slice(1, -1), target));
    const stubbed = keepStubs(orthogonal);
    return removeRedundantPoints(orthogonalize(source, stubbed.slice(1, -1), target)).slice(1, -1);
}

/**
 * The waypoint-free shape, used while a node is dragged or animated and when the router
 * finds no route. It avoids nothing. Forward: a riser at mid x. Backward or stacked: out STUB,
 * a return leg at the ports' mid y, or below both when they sit on about the same row, then in STUB.
 */
export function fallbackRoutePoints(source: IPoint, target: IPoint): IPoint[] {
    const exitX = source.x + STUB;
    const entryX = target.x - STUB;
    if (entryX >= exitX) {
        const middleX = (source.x + target.x) / 2;
        return [source, { x: middleX, y: source.y }, { x: middleX, y: target.y }, target];
    }
    const legY =
        Math.abs(target.y - source.y) >= MIN_RETURN_GAP
            ? (source.y + target.y) / 2
            : Math.max(source.y, target.y) + RETURN_DROP;
    return [
        source,
        { x: exitX, y: source.y },
        { x: exitX, y: legY },
        { x: entryX, y: legY },
        { x: entryX, y: target.y },
        target,
    ];
}

// [source, ...waypoints, target] as copies, the first and last waypoints snapped onto the port
// rows when within 3 px.
function snappedAnchors(source: IPoint, waypoints: IPoint[], target: IPoint): IPoint[] {
    const anchors = [source, ...waypoints.map((point) => ({ x: point.x, y: point.y })), target];
    const last = anchors.length - 1;
    if (last >= 2) {
        if (Math.abs(anchors[1].y - source.y) <= SNAP_TOLERANCE) anchors[1].y = source.y;
        if (Math.abs(anchors[last - 1].y - target.y) <= SNAP_TOLERANCE) anchors[last - 1].y = target.y;
    }
    return anchors;
}

// Each waypoint off the line its neighbours share becomes that stretch, moved through it. A
// waypoint within 3 px of the line is snapped onto it, for removeRedundantPoints to drop. A bend
// (on one axis with the previous point, the other with the next) is left alone.
function moveDraggedStretches(anchors: IPoint[]): IPoint[] {
    const source = anchors[0];
    const target = anchors[anchors.length - 1];
    const result = [source];
    for (let index = 1; index < anchors.length - 1; index++) {
        const previous = result[result.length - 1];
        const point = anchors[index];
        const next = anchors[index + 1];
        const isBend = (point.x === previous.x && point.y === next.y) || (point.y === previous.y && point.x === next.x);
        if (!isBend && Math.abs(previous.x - next.x) <= SNAP_TOLERANCE) {
            if (Math.abs(point.x - previous.x) <= SNAP_TOLERANCE) {
                result.push({ x: previous.x, y: point.y });
            } else {
                // A riser that ends on a port row stops at that port's stub end.
                let x = point.x;
                if (index === 2 && previous.y === source.y) x = Math.max(x, source.x + STUB);
                if (index === anchors.length - 3 && next.y === target.y) x = Math.min(x, target.x - STUB);
                result.push({ x, y: previous.y }, { x, y: next.y });
            }
        } else if (!isBend && Math.abs(previous.y - next.y) <= SNAP_TOLERANCE) {
            if (Math.abs(point.y - previous.y) <= SNAP_TOLERANCE) {
                result.push({ x: point.x, y: previous.y });
                continue;
            }
            // A leg next to a port starts or ends at its stub end, which stays in the list.
            const from = index === 1 ? { x: source.x + STUB, y: source.y } : previous;
            const to = index === anchors.length - 2 ? { x: target.x - STUB, y: target.y } : next;
            if (from !== previous) result.push(from);
            result.push({ x: from.x, y: point.y }, { x: to.x, y: point.y });
            if (to !== next) result.push(to);
        } else {
            result.push(point);
        }
    }
    result.push(target);
    return result;
}

// Drops every interior point on one line with both neighbours, backtracks included, until none is
// left. A backtrack next to a port stays when dropping it would turn the port leg around.
function removeRedundantPoints(points: IPoint[]): IPoint[] {
    const result = [...points];
    const last = (): number => result.length - 1;
    let index = 1;
    while (index < last()) {
        const previous = result[index - 1];
        const point = result[index];
        const next = result[index + 1];
        const onVertical = previous.x === point.x && point.x === next.x;
        const onHorizontal = previous.y === point.y && point.y === next.y;
        const turnsSourceLegAround = index === 1 && onHorizontal && next.x <= previous.x;
        const turnsTargetLegAround = index === last() - 1 && onHorizontal && previous.x >= next.x;
        if ((onVertical || onHorizontal) && !turnsSourceLegAround && !turnsTargetLegAround) {
            result.splice(index, 1);
            index = Math.max(1, index - 1);
        } else {
            index++;
        }
    }
    return result;
}

// Stubs stay at least STUB long: a first bend closer than STUB to the source (or left of it) moves out to source.x + STUB,
// with the bend that shares its x; the same at the target. Elbows the move breaks are redrawn after.
function keepStubs(points: IPoint[]): IPoint[] {
    const result = points.map((point) => ({ x: point.x, y: point.y }));
    const last = result.length - 1;
    if (last < 2) return result;
    const shiftBend = (index: number, partnerIndex: number, x: number): void => {
        const partner = result[partnerIndex];
        if (partnerIndex > 0 && partnerIndex < last && partner.x === result[index].x) partner.x = x;
        result[index].x = x;
    };
    const exitX = result[0].x + STUB;
    if (result[1].x < exitX) shiftBend(1, 2, exitX);
    const entryX = result[last].x - STUB;
    if (result[last - 1].x > entryX) shiftBend(last - 1, last - 2, entryX);
    return result;
}

function getBend(previous: IPoint, corner: IPoint, next: IPoint, size: number): string {
    const bendSize = Math.min(distance(previous, corner) / 2, distance(corner, next) / 2, size);
    const { x, y } = corner;

    if ((previous.x === x && x === next.x) || (previous.y === y && y === next.y)) {
        return `L ${x} ${y}`;
    }

    if (previous.y === y) {
        const xDirection = previous.x < next.x ? -1 : 1;
        const yDirection = previous.y < next.y ? 1 : -1;
        return `L ${x + bendSize * xDirection},${y} Q ${x},${y} ${x},${y + bendSize * yDirection}`;
    }

    const xDirection = previous.x < next.x ? 1 : -1;
    const yDirection = previous.y < next.y ? -1 : 1;
    return `L ${x},${y + bendSize * yDirection} Q ${x},${y} ${x + bendSize * xDirection},${y}`;
}

function distance(from: IPoint, to: IPoint): number {
    return Math.sqrt(Math.pow(to.x - from.x, 2) + Math.pow(to.y - from.y, 2));
}
