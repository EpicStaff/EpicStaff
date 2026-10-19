import { IPoint } from '@foblex/2d';

import { segmentsIntersect } from '../geometry/segment-math';

// Whether a wire crosses itself, as the quality metrics count it. Unlike their proper-crossing
// test between wires, touching or a collinear overlap between non-adjacent segments counts.

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
