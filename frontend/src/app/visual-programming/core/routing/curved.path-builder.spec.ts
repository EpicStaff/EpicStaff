import { EFConnectableSide, IFConnectionBuilderRequest } from '@foblex/flow';

import { CurvedPathBuilder } from './curved.path-builder';

function request(
    source: { x: number; y: number },
    target: { x: number; y: number },
    waypoints: IFConnectionBuilderRequest['waypoints'] = []
): IFConnectionBuilderRequest {
    return {
        source,
        sourceSide: EFConnectableSide.RIGHT,
        target,
        targetSide: EFConnectableSide.LEFT,
        radius: 8,
        offset: 0,
        waypoints,
    };
}

describe('CurvedPathBuilder', () => {
    const builder = new CurvedPathBuilder();

    describe('with waypoints', () => {
        it('returns a valid SVG path string', () => {
            const response = builder.handle(
                request({ x: 0, y: 0 }, { x: 300, y: 100 }, [
                    { x: 100, y: 20 },
                    { x: 200, y: 80 },
                ])
            );

            expect(response.path).toMatch(/^M /);
            expect(response.path).toContain('C');
        });

        it('candidates is an empty array', () => {
            const response = builder.handle(request({ x: 0, y: 0 }, { x: 300, y: 100 }, [{ x: 150, y: 50 }]));

            expect(response.candidates).toEqual([]);
        });

        it('secondPoint is the first waypoint', () => {
            const waypoint = { x: 100, y: 20 };
            const response = builder.handle(request({ x: 0, y: 0 }, { x: 300, y: 100 }, [waypoint]));

            expect(response.secondPoint).toEqual(waypoint);
        });

        it('penultimatePoint is the last waypoint', () => {
            const waypoints = [
                { x: 100, y: 20 },
                { x: 200, y: 80 },
            ];
            const response = builder.handle(request({ x: 0, y: 0 }, { x: 300, y: 100 }, waypoints));

            expect(response.penultimatePoint).toEqual(waypoints[1]);
        });

        it('points includes source, waypoints, and target', () => {
            const source = { x: 0, y: 0 };
            const target = { x: 300, y: 100 };
            const waypoints = [
                { x: 100, y: 20 },
                { x: 200, y: 80 },
            ];
            const response = builder.handle(request(source, target, waypoints));

            expect(response.points).toEqual([source, ...waypoints, target]);
        });
    });

    describe('without waypoints (forward)', () => {
        it('returns a smooth curve path without L commands', () => {
            const response = builder.handle(request({ x: 0, y: 0 }, { x: 400, y: 100 }));

            expect(response.path).toMatch(/^M /);
            expect(response.path).toContain('C');
            expect(response.path).not.toMatch(/\bL\b/);
        });

        it('connects source to target', () => {
            const source = { x: 0, y: 0 };
            const target = { x: 400, y: 100 };
            const response = builder.handle(request(source, target));

            expect(response.points[0]).toEqual(source);
            expect(response.points[response.points.length - 1]).toEqual(target);
        });

        it('candidates is empty', () => {
            const response = builder.handle(request({ x: 0, y: 0 }, { x: 400, y: 100 }));

            expect(response.candidates).toEqual([]);
        });
    });

    describe('without waypoints (backward)', () => {
        it('returns a curve that loops with more points than forward', () => {
            // Backward: target.x is well left of source.x (beyond the 20 px threshold)
            const forwardResponse = builder.handle(request({ x: 0, y: 0 }, { x: 400, y: 100 }));
            const backwardResponse = builder.handle(request({ x: 400, y: 100 }, { x: 0, y: 0 }));

            // Backward uses computeBackwardControlPoints which returns 4 points
            // vs forward's computeForwardControlPoints which returns 2
            expect(backwardResponse.points.length).toBeGreaterThan(forwardResponse.points.length);
        });

        it('candidates is empty', () => {
            const response = builder.handle(request({ x: 400, y: 100 }, { x: 0, y: 0 }));

            expect(response.candidates).toEqual([]);
        });
    });
});
