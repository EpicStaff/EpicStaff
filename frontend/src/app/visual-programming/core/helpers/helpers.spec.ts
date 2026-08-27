import { ConnectionModel } from '../models/connection.model';
import { BaseNodeModel } from '../models/node.model';
import { isBackwardConnection } from './helpers';

function node(
    id: string,
    x: number,
    y: number,
    width: number,
    height: number,
    portId: string,
    portPosition: string
): BaseNodeModel {
    return {
        id,
        position: { x, y },
        size: { width, height },
        ports: [{ id: portId, position: portPosition }],
    } as unknown as BaseNodeModel;
}

function connection(
    sourceNodeId: string,
    sourcePortId: string,
    targetNodeId: string,
    targetPortId: string
): ConnectionModel {
    return {
        id: 'conn-1',
        sourceNodeId,
        targetNodeId,
        sourcePortId,
        targetPortId,
    } as unknown as ConnectionModel;
}

describe('isBackwardConnection', () => {
    it('is false for a horizontal forward connection (source left of target)', () => {
        const source = node('source', 0, 0, 100, 60, 'source_out-right', 'right');
        const target = node('target', 300, 0, 100, 60, 'target_in-left', 'left');
        const conn = connection('source', 'source_out-right', 'target', 'target_in-left');

        expect(isBackwardConnection(conn, [source, target])).toBe(false);
    });

    it('is true for a horizontal backward connection (source exit past target entry)', () => {
        const source = node('source', 300, 0, 100, 60, 'source_out-right', 'right');
        const target = node('target', 0, 0, 100, 60, 'target_in-left', 'left');
        const conn = connection('source', 'source_out-right', 'target', 'target_in-left');

        expect(isBackwardConnection(conn, [source, target])).toBe(true);
    });

    it('is false for a vertical forward connection (source above target)', () => {
        const source = node('source', 0, 0, 100, 100, 'source_out-bottom', 'bottom');
        const target = node('target', 0, 300, 100, 100, 'target_in-top', 'top');
        const conn = connection('source', 'source_out-bottom', 'target', 'target_in-top');

        expect(isBackwardConnection(conn, [source, target])).toBe(false);
    });

    it('is true for a vertical backward connection (source exit past target entry)', () => {
        const source = node('source', 0, 300, 100, 100, 'source_out-bottom', 'bottom');
        const target = node('target', 0, 0, 100, 100, 'target_in-top', 'top');
        const conn = connection('source', 'source_out-bottom', 'target', 'target_in-top');

        expect(isBackwardConnection(conn, [source, target])).toBe(true);
    });

    it('flips from backward to forward when the target moves past the source exit edge', () => {
        const source = node('source', 300, 0, 100, 60, 'source_out-right', 'right');
        const backwardTarget = node('target', 0, 0, 100, 60, 'target_in-left', 'left');
        const conn = connection('source', 'source_out-right', 'target', 'target_in-left');

        expect(isBackwardConnection(conn, [source, backwardTarget])).toBe(true);

        const forwardTarget = node('target', 500, 0, 100, 60, 'target_in-left', 'left');

        expect(isBackwardConnection(conn, [source, forwardTarget])).toBe(false);
    });

    it('is false when either node is missing', () => {
        const source = node('source', 0, 0, 100, 60, 'source_out-right', 'right');
        const conn = connection('source', 'source_out-right', 'missing-target', 'target_in-left');

        expect(isBackwardConnection(conn, [source])).toBe(false);
    });
});
