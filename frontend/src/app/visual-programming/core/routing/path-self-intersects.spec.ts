import { IPoint } from '@foblex/2d';

import { pathSelfIntersects } from './path-self-intersects';

function pt(x: number, y: number): IPoint {
    return { x, y };
}

describe('pathSelfIntersects', () => {
    it('detects a self-crossing 4-point path (bowtie)', () => {
        const path = [pt(0, 0), pt(10, 10), pt(10, 0), pt(0, 10)];

        expect(pathSelfIntersects(path)).toBe(true);
    });

    it('accepts a normal orthogonal zigzag with no self-crossing', () => {
        const path = [pt(0, 0), pt(0, 10), pt(20, 10), pt(20, 20)];

        expect(pathSelfIntersects(path)).toBe(false);
    });

    it('flags a path whose later segment doubles back onto an earlier one', () => {
        const path = [pt(0, 0), pt(20, 0), pt(20, 10), pt(5, 0)];

        expect(pathSelfIntersects(path)).toBe(true);
    });

    it('does not flag two adjacent segments sharing an endpoint', () => {
        const path = [pt(0, 0), pt(10, 0), pt(10, 10)];

        expect(pathSelfIntersects(path)).toBe(false);
    });
});
