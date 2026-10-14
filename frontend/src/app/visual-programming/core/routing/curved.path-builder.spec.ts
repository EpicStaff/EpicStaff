import { EFConnectableSide, IFConnectionBuilderRequest } from '@foblex/flow';

import { CurvedPathBuilder, curveHitsObstacle } from './curved.path-builder';
import { Rect } from './obstacles';

function request(
    source: { x: number; y: number },
    target: { x: number; y: number },
    waypoints: { x: number; y: number }[] = []
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
        it('very close points produce a straight line', () => {
            const response = builder.handle(request({ x: 0, y: 0 }, { x: 40, y: 0 }));

            expect(response.path).toContain('M 0 0');
            expect(response.path).toContain('L');
            expect(response.path.match(/ A /g)).toBeNull();
            expect(response.points.length).toBe(2);
        });

        it('small positive gap within threshold produces straight line', () => {
            const response = builder.handle(request({ x: 0, y: 0 }, { x: 50, y: 50 }));

            expect(response.points.length).toBe(2);
        });

        it('same point produces straight line', () => {
            const response = builder.handle(request({ x: 100, y: 100 }, { x: 100, y: 100 }));

            expect(response.path).toContain('M 100 100');
            expect(response.points.length).toBe(2);
        });

        it('points beyond threshold still use curved path', () => {
            const response = builder.handle(request({ x: 0, y: 0 }, { x: 200, y: 0 }));

            // Forward curve: exitX=20, entryX=180, forward path with 4 points
            expect(response.points.length).toBe(4);
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

    describe('backward S-curve (target lower-left of source)', () => {
        const source = { x: 300, y: 0 };
        const target = { x: 0, y: 200 };

        it('uses SVG arc commands for the two arc segments', () => {
            const response = builder.handle(request(source, target));

            expect(response.path).toContain(' A ');
            expect(response.path.match(/ A /g)?.length).toBe(2);
        });

        it('has 6 points and routes between nodes', () => {
            const response = builder.handle(request(source, target));

            expect(response.points.length).toBe(6);
            const tExit = response.points[2];
            const tEntry = response.points[3];
            // tExit is below source, tEntry is above target (between them)
            expect(tExit.y).toBeGreaterThan(source.y);
            expect(tEntry.y).toBeLessThan(target.y);
        });
    });

    describe('backward loop (insufficient vertical gap)', () => {
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

    describe('waypoint-driven fallback', () => {
        it('uses smooth curve when no waypoints are present', () => {
            const response = builder.handle(request({ x: 0, y: 50 }, { x: 300, y: 50 }));

            expect(response.path).toContain('C');
        });

        it('uses rounded orthogonal path when waypoints are present', () => {
            const waypoints = [
                { x: 20, y: 50 },
                { x: 20, y: 0 },
                { x: 280, y: 0 },
                { x: 280, y: 50 },
            ];
            const response = builder.handle(request({ x: 0, y: 50 }, { x: 300, y: 50 }, waypoints));

            expect(response.path).not.toContain('C');
            expect(response.path).toContain('Q');
            expect(response.points.length).toBe(waypoints.length + 2);
        });
    });

    describe('curveHitsObstacle', () => {
        const obstacleInPath: Rect = { left: 100, top: 20, right: 200, bottom: 80 };

        it('returns false when no obstacles', () => {
            expect(curveHitsObstacle({ x: 0, y: 50 }, { x: 300, y: 50 }, [])).toBe(false);
        });

        it('returns false when obstacle is far from curve', () => {
            const farObstacle: Rect = { left: 400, top: 400, right: 500, bottom: 500 };

            expect(curveHitsObstacle({ x: 0, y: 50 }, { x: 300, y: 50 }, [farObstacle])).toBe(false);
        });

        it('returns true when forward curve passes through obstacle', () => {
            expect(curveHitsObstacle({ x: 0, y: 50 }, { x: 300, y: 50 }, [obstacleInPath])).toBe(true);
        });

        it('excludes source and target node obstacles', () => {
            const sourceObstacle: Rect = { left: -10, top: 30, right: 30, bottom: 70 };

            expect(curveHitsObstacle({ x: 0, y: 50 }, { x: 300, y: 50 }, [sourceObstacle])).toBe(false);
        });

        it('detects backward S-curve hitting obstacle', () => {
            const middleObstacle: Rect = { left: 100, top: 50, right: 200, bottom: 150 };

            expect(curveHitsObstacle({ x: 300, y: 200 }, { x: 0, y: 0 }, [middleObstacle])).toBe(true);
        });
    });
});
