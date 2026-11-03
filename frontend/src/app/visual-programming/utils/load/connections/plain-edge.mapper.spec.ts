import { NodeType } from '@shared/models';

import { Edge } from '../../../core/models/edge.model';
import { NodeModel } from '../../../core/models/node.model';
import { mapEdgesToConnections } from './plain-edge.mapper';

function mapWithMetadata(metadata: Record<string, unknown>) {
    const edge: Edge = { id: 1, start_node_id: 1, end_node_id: 2, graph: 1, metadata };
    const nodeByBackendId = new Map<number, NodeModel>([
        [1, { type: NodeType.PYTHON } as NodeModel],
        [2, { type: NodeType.PYTHON } as NodeModel],
    ]);
    const [connection] = mapEdgesToConnections(
        [edge],
        new Map([
            [1, 'source-uuid'],
            [2, 'target-uuid'],
        ]),
        nodeByBackendId
    );
    return connection;
}

describe('mapEdgesToConnections persisted waypoints', () => {
    it('keeps a valid waypoint list and marks the connection as user adjusted', () => {
        const connection = mapWithMetadata({
            waypoints: [
                { x: 10, y: 20 },
                { x: -30.5, y: 40 },
            ],
        });

        expect(connection.waypoints).toEqual([
            { x: 10, y: 20 },
            { x: -30.5, y: 40 },
        ]);
        expect(connection.userAdjustedWaypoints).toBe(true);
    });

    it('clamps huge coordinates', () => {
        const connection = mapWithMetadata({
            waypoints: [
                { x: 1e20, y: -1e20 },
                { x: 1_000_001, y: 5 },
            ],
        });

        expect(connection.waypoints).toEqual([
            { x: 1_000_000, y: -1_000_000 },
            { x: 1_000_000, y: 5 },
        ]);
    });

    it.each([
        ['NaN', { x: NaN, y: 1 }],
        ['Infinity', { x: 1, y: Infinity }],
        ['a string coordinate', { x: '1', y: 1 }],
        ['a missing coordinate', { x: 1 }],
        ['null', null],
        ['a number', 7],
    ])('rejects the whole list when one entry is %s', (_label, invalidEntry) => {
        const connection = mapWithMetadata({ waypoints: [{ x: 1, y: 1 }, invalidEntry, { x: 2, y: 2 }] });

        expect(connection.waypoints).toBeUndefined();
        expect(connection.userAdjustedWaypoints).toBeUndefined();
    });

    it.each([
        ['a non-array', { x: 1, y: 1 }],
        ['an empty array', []],
        ['missing', undefined],
    ])('yields no waypoints when the value is %s', (_label, value) => {
        const connection = mapWithMetadata({ waypoints: value });

        expect(connection.waypoints).toBeUndefined();
        expect(connection.userAdjustedWaypoints).toBeUndefined();
    });
});
