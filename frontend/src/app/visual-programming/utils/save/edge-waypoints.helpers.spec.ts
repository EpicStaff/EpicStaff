import { ConnectionModel } from '../../core/models/connection.model';
import { FlowModel } from '../../core/models/flow.model';
import { toDirtyComparableFlowState } from './edge-waypoints.helpers';

function connection(id: string, waypoints: { x: number; y: number }[], userAdjusted?: boolean): ConnectionModel {
    return {
        id,
        sourceNodeId: 'a',
        targetNodeId: 'b',
        waypoints,
        userAdjustedWaypoints: userAdjusted,
    } as unknown as ConnectionModel;
}

describe('toDirtyComparableFlowState', () => {
    it('ignores waypoints diverging on a non-user-adjusted connection', () => {
        const baseline: FlowModel = { nodes: [], connections: [connection('c', [{ x: 1, y: 1 }])] };
        const current: FlowModel = { nodes: [], connections: [connection('c', [{ x: 9, y: 9 }])] };

        const result = toDirtyComparableFlowState(current);
        const baselineResult = toDirtyComparableFlowState(baseline);

        expect(JSON.stringify(result)).toBe(JSON.stringify(baselineResult));
    });

    it('keeps waypoints diverging on a user-adjusted connection', () => {
        const baseline: FlowModel = { nodes: [], connections: [connection('c', [{ x: 1, y: 1 }], true)] };
        const current: FlowModel = { nodes: [], connections: [connection('c', [{ x: 9, y: 9 }], true)] };

        const result = toDirtyComparableFlowState(current);
        const baselineResult = toDirtyComparableFlowState(baseline);

        expect(JSON.stringify(result)).not.toBe(JSON.stringify(baselineResult));
    });

    it('does not mutate the input flow state', () => {
        const conn = connection('c', [{ x: 1, y: 1 }]);
        const flow: FlowModel = { nodes: [], connections: [conn] };

        toDirtyComparableFlowState(flow);

        expect(flow.connections[0].waypoints).toEqual([{ x: 1, y: 1 }]);
        expect(flow.connections[0]).toBe(conn);
    });
});
