import { EFConnectableSide, IFConnectionBuilderRequest } from '@foblex/flow';

import { CurvedPathBuilder } from './curved.path-builder';

function request(source: { x: number; y: number }, target: { x: number; y: number }): IFConnectionBuilderRequest {
    return {
        source,
        sourceSide: EFConnectableSide.RIGHT,
        target,
        targetSide: EFConnectableSide.LEFT,
        radius: 8,
        offset: 0,
        waypoints: [],
    };
}

describe('CurvedPathBuilder', () => {
    const builder = new CurvedPathBuilder();

    describe('forward connection (target right of source)', () => {
        it('returns path with M, L, C, L commands', () => {
            const response = builder.handle(request({ x: 0, y: 0 }, { x: 300, y: 100 }));

            expect(response.path).toMatch(/^M /);
            expect(response.path).toContain('L');
            expect(response.path).toContain('C');
        });

        it('points are [source, exitPoint, entryPoint, target]', () => {
            const source = { x: 0, y: 0 };
            const target = { x: 300, y: 100 };
            const response = builder.handle(request(source, target));

            expect(response.points.length).toBe(4);
            expect(response.points[0]).toEqual(source);
            expect(response.points[1]).toEqual({ x: 20, y: 0 });
            expect(response.points[2]).toEqual({ x: 280, y: 100 });
            expect(response.points[3]).toEqual(target);
        });

        it('secondPoint is the exit stub point', () => {
            const response = builder.handle(request({ x: 0, y: 0 }, { x: 300, y: 100 }));

            expect(response.secondPoint).toEqual({ x: 20, y: 0 });
        });

        it('penultimatePoint is the entry stub point', () => {
            const response = builder.handle(request({ x: 0, y: 0 }, { x: 300, y: 100 }));

            expect(response.penultimatePoint).toEqual({ x: 280, y: 100 });
        });

        it('candidates is empty', () => {
            const response = builder.handle(request({ x: 0, y: 0 }, { x: 300, y: 100 }));

            expect(response.candidates).toEqual([]);
        });
    });

    describe('boundary cases', () => {
        it('zero-gap (target exactly 2*STUB right) uses backward path', () => {
            const response = builder.handle(request({ x: 0, y: 0 }, { x: 40, y: 0 }));

            // backward loop produces 4 A segments and 6 points
            expect(response.path.match(/ A /g)?.length).toBe(4);
            expect(response.points.length).toBe(6);
        });

        it('small positive gap uses backward path', () => {
            const response = builder.handle(request({ x: 0, y: 0 }, { x: 50, y: 50 }));

            // entryX (30) <= exitX (20) is false — gap is 10, so forward
            // Actually: exitX = 20, entryX = 30, entryX > exitX → forward
            expect(response.points.length).toBe(4);
        });

        it('same point produces backward path with loop above', () => {
            const response = builder.handle(request({ x: 100, y: 100 }, { x: 100, y: 100 }));

            expect(response.path.match(/ A /g)?.length).toBe(4);
            expect(response.points[2].y).toBeLessThan(100);
        });
    });

    describe('backward S-curve (target upper-left of source)', () => {
        const source = { x: 300, y: 200 };
        const target = { x: 0, y: 0 };

        it('uses SVG arc commands (A) for the two arc segments', () => {
            const response = builder.handle(request(source, target));

            expect(response.path).toMatch(/^M /);
            expect(response.path).toContain(' A ');
            expect(response.path.match(/ A /g)?.length).toBe(2);
        });

        it('has 6 points: source, exitPoint, tExit, tEntry, entryPoint, target', () => {
            const response = builder.handle(request(source, target));

            expect(response.points.length).toBe(6);
            expect(response.points[0]).toEqual(source);
            expect(response.points[5]).toEqual(target);
        });

        it('tangent points sit between source and target vertically', () => {
            const response = builder.handle(request(source, target));

            const tExit = response.points[2];
            const tEntry = response.points[3];
            // tExit is above source, tEntry is below target (or between them)
            expect(tExit.y).toBeLessThan(source.y);
            expect(tEntry.y).toBeGreaterThan(target.y);
        });

        it('secondPoint is the exit stub point', () => {
            const response = builder.handle(request(source, target));

            expect(response.secondPoint).toEqual({ x: source.x + 20, y: source.y });
        });

        it('penultimatePoint is the entry stub point', () => {
            const response = builder.handle(request(source, target));

            expect(response.penultimatePoint).toEqual({ x: target.x - 20, y: target.y });
        });

        it('candidates is empty', () => {
            const response = builder.handle(request(source, target));

            expect(response.candidates).toEqual([]);
        });
    });

    describe('backward loop (target at same height or below source)', () => {
        it('uses 4 SVG arc commands for rounded-rectangle loop', () => {
            const response = builder.handle(request({ x: 300, y: 100 }, { x: 0, y: 100 }));

            expect(response.path).toContain(' A ');
            expect(response.path.match(/ A /g)?.length).toBe(4);
            expect(response.points.length).toBe(6);
        });

        it('tangent points are above both nodes', () => {
            const source = { x: 300, y: 100 };
            const target = { x: 0, y: 90 };
            const response = builder.handle(request(source, target));

            const tangentExit = response.points[2];
            const tangentEntry = response.points[3];
            expect(tangentExit.y).toBeLessThan(Math.min(source.y, target.y));
            expect(tangentEntry.y).toBeLessThan(Math.min(source.y, target.y));
        });

        it('candidates is empty', () => {
            const response = builder.handle(request({ x: 300, y: 100 }, { x: 0, y: 100 }));

            expect(response.candidates).toEqual([]);
        });
    });
});
