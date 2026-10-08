import { NodeType } from '@shared/models';

import { connect, makeNode, withPorts } from '../layout/testing/fixtures';
import { ConnectionModel } from '../models/connection.model';
import { NodeModel } from '../models/node.model';
import { routeAllCurved } from './curved-route-all';

function python(id: string, x: number, y: number): NodeModel {
    return makeNode(id, NodeType.PYTHON, { height: 60, position: { x, y } });
}

function wired(
    nodes: NodeModel[],
    connections: ConnectionModel[]
): { nodes: NodeModel[]; connections: ConnectionModel[] } {
    return { nodes: withPorts(nodes, connections), connections };
}

describe('routeAllCurved', () => {
    it('returns non-empty through-points for a forward connection', () => {
        const fixture = wired([python('a', 0, 0), python('b', 600, 0)], [connect('w', 'a', 'out', 'b', 'in')]);

        const routes = routeAllCurved(fixture.nodes, fixture.connections);

        expect(routes.has('w')).toBe(true);
        // Forward connections produce 2 control points
        expect(routes.get('w')!.length).toBeGreaterThanOrEqual(2);
    });

    it('returns through-points that loop above for a backward connection', () => {
        const fixture = wired([python('a', 0, 0), python('b', 600, 0)], [connect('w', 'b', 'out', 'a', 'in')]);

        const routes = routeAllCurved(fixture.nodes, fixture.connections);

        expect(routes.has('w')).toBe(true);
        const points = routes.get('w')!;
        // Backward connections produce 4 through-points (exit stub, top right, top left, entry stub)
        expect(points.length).toBe(4);
        // The middle two points should be above both nodes (y < node top)
        expect(points[1].y).toBeLessThan(0);
        expect(points[2].y).toBeLessThan(0);
    });

    it('skips connections with userAdjustedWaypoints', () => {
        const connections: ConnectionModel[] = [
            {
                ...connect('w', 'a', 'out', 'b', 'in'),
                userAdjustedWaypoints: true,
                waypoints: [{ x: 300, y: 50 }],
            },
        ];
        const fixture = wired([python('a', 0, 0), python('b', 600, 0)], connections);

        const routes = routeAllCurved(fixture.nodes, fixture.connections);

        expect(routes.has('w')).toBe(false);
    });

    it('returns an empty map for an empty connections array', () => {
        const routes = routeAllCurved([python('a', 0, 0)], []);

        expect(routes.size).toBe(0);
    });

    it('skips stale connections without throwing', () => {
        const nodes = withPorts([python('a', 0, 0), python('b', 600, 0)], [connect('ok', 'a', 'out', 'b', 'in')]);
        const connections = [connect('ok', 'a', 'out', 'b', 'in'), connect('ghost', 'a', 'out', 'missing', 'in')];

        const routes = routeAllCurved(nodes, connections);

        expect([...routes.keys()]).toEqual(['ok']);
    });
});
