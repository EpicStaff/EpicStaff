import { IPoint } from '@foblex/2d';

// Whether a wire crosses itself, as the quality metrics count it. Unlike their proper-crossing
// test between wires, touching or a collinear overlap between non-adjacent segments counts.

function orientation(a: IPoint, b: IPoint, c: IPoint): number {
    const value = (b.y - a.y) * (c.x - b.x) - (b.x - a.x) * (c.y - b.y);

    if (Math.abs(value) < 0.0001) return 0;

    return value > 0 ? 1 : 2;
}

function onSegment(a: IPoint, b: IPoint, c: IPoint): boolean {
    return (
        b.x <= Math.max(a.x, c.x) + 0.0001 &&
        b.x >= Math.min(a.x, c.x) - 0.0001 &&
        b.y <= Math.max(a.y, c.y) + 0.0001 &&
        b.y >= Math.min(a.y, c.y) - 0.0001
    );
}

function segmentsIntersect(p1: IPoint, q1: IPoint, p2: IPoint, q2: IPoint): boolean {
    const o1 = orientation(p1, q1, p2);
    const o2 = orientation(p1, q1, q2);
    const o3 = orientation(p2, q2, p1);
    const o4 = orientation(p2, q2, q1);

    if (o1 !== o2 && o3 !== o4) return true;

    if (o1 === 0 && onSegment(p1, p2, q1)) return true;
    if (o2 === 0 && onSegment(p1, q2, q1)) return true;
    if (o3 === 0 && onSegment(p2, p1, q2)) return true;
    if (o4 === 0 && onSegment(p2, q1, q2)) return true;

    return false;
}

export function pathSelfIntersects(path: IPoint[]): boolean {
    for (let i = 0; i < path.length - 1; i++) {
        for (let j = i + 2; j < path.length - 1; j++) {
            if (segmentsIntersect(path[i], path[i + 1], path[j], path[j + 1])) {
                return true;
            }
        }
    }

    return false;
}
