import { EFConnectableSide, IFConnectionBuilderRequest } from '@foblex/flow';

import { OrthogonalPathBuilder } from './orthogonal.path-builder';
import { buildRoundedOrthogonalPath, fallbackRoutePoints } from './orthogonal-route-shapes';

function request(waypoints: IFConnectionBuilderRequest['waypoints']): IFConnectionBuilderRequest {
    return {
        source: { x: 0, y: 0 },
        sourceSide: EFConnectableSide.RIGHT,
        target: { x: 80, y: 100 },
        targetSide: EFConnectableSide.LEFT,
        radius: 8,
        offset: 0,
        waypoints,
    };
}

describe('OrthogonalPathBuilder', () => {
    it('draws [source, ...waypoints, target] with rounded corners', () => {
        const response = new OrthogonalPathBuilder().handle(
            request([
                { x: 40, y: 0 },
                { x: 40, y: 100 },
            ])
        );

        const points = [
            { x: 0, y: 0 },
            { x: 40, y: 0 },
            { x: 40, y: 100 },
            { x: 80, y: 100 },
        ];
        expect(response.points).toEqual(points);
        expect(response.path).toBe(buildRoundedOrthogonalPath(points, 8));
        expect(response.secondPoint).toEqual({ x: 40, y: 0 });
        expect(response.penultimatePoint).toEqual({ x: 40, y: 100 });
    });

    it('puts one candidate on the middle of each segment, in waypoint insert order', () => {
        const response = new OrthogonalPathBuilder().handle(
            request([
                { x: 40, y: 0 },
                { x: 40, y: 100 },
            ])
        );

        // Foblex inserts candidate i at waypoint index i, so candidate i must sit between
        // waypoints i-1 and i: the source stub, the riser, the target stub.
        expect(response.candidates).toEqual([
            { x: 20, y: 0 },
            { x: 40, y: 50 },
            { x: 60, y: 100 },
        ]);
    });

    it('snaps waypoints a DOM pixel or two off the port rows and turns a diagonal into an elbow', () => {
        const response = new OrthogonalPathBuilder().handle(request([{ x: 40, y: 2 }]));

        expect(response.points).toEqual([
            { x: 0, y: 0 },
            { x: 40, y: 0 },
            { x: 40, y: 100 },
            { x: 80, y: 100 },
        ]);
        // Two stretches (source → waypoint, waypoint → elbow → target): two candidates.
        expect(response.candidates).toEqual([
            { x: 20, y: 0 },
            { x: 40, y: 50 },
        ]);
    });

    it('draws a dragged candidate as the moved riser, candidates still on the raw points', () => {
        // Foblex inserted the riser's candidate at index 1 and the drag moved it 20 px right.
        const response = new OrthogonalPathBuilder().handle(
            request([
                { x: 40, y: 0 },
                { x: 60, y: 50 },
                { x: 40, y: 100 },
            ])
        );

        expect(response.points).toEqual([
            { x: 0, y: 0 },
            { x: 60, y: 0 },
            { x: 60, y: 100 },
            { x: 80, y: 100 },
        ]);
        expect(response.secondPoint).toEqual({ x: 60, y: 0 });
        expect(response.penultimatePoint).toEqual({ x: 60, y: 100 });
        // Foblex's insert index counts the raw list: one candidate per raw stretch.
        expect(response.candidates).toEqual([
            { x: 20, y: 0 },
            { x: 50, y: 0 },
            { x: 60, y: 75 },
            { x: 60, y: 100 },
        ]);
    });

    it('draws the fallback shape when there are no waypoints', () => {
        const response = new OrthogonalPathBuilder().handle(request([]));

        expect(response.points).toEqual(fallbackRoutePoints({ x: 0, y: 0 }, { x: 80, y: 100 }));
        expect(response.candidates).toEqual([{ x: 40, y: 50 }]); // the middle of the riser
    });
});
