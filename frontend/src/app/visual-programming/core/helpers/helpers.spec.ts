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

    it('stays true for a horizontally-backward connection regardless of the vertical gap between nodes', () => {
        const source = node('source', 100, 300, 330, 60, 'source_out-right', 'right');
        const conn = connection('source', 'source_out-right', 'target', 'target_in-left');

        for (const dy of [5, 25, 40, 60, 120, 200]) {
            const target = node('target', 100, 300 + dy, 330, 60, 'target_in-left', 'left');

            expect(isBackwardConnection(conn, [source, target])).toBe(true);
        }
    });

    it('stays false for a vertically-forward connection regardless of the horizontal gap between nodes', () => {
        const source = node('source', 100, 0, 100, 60, 'source_out-bottom', 'bottom');
        const conn = connection('source', 'source_out-bottom', 'target', 'target_in-top');

        for (const dx of [5, 25, 40, 60, 120, 200]) {
            const target = node('target', 100 + dx, 200, 100, 60, 'target_in-top', 'top');

            expect(isBackwardConnection(conn, [source, target])).toBe(false);
        }
    });

    it('does not throw for mixed port orientations (falls back to layout dominance)', () => {
        const rightToTop = node('source', 0, 0, 100, 60, 'source_out-right', 'right');
        const topTarget = node('target', 300, 0, 100, 60, 'target_in-top', 'top');
        const c1 = connection('source', 'source_out-right', 'target', 'target_in-top');

        expect(() => isBackwardConnection(c1, [rightToTop, topTarget])).not.toThrow();

        const bottomSource = node('source', 0, 0, 100, 60, 'source_out-bottom', 'bottom');
        const leftTarget = node('target', 0, 300, 100, 60, 'target_in-left', 'left');
        const c2 = connection('source', 'source_out-bottom', 'target', 'target_in-left');

        expect(() => isBackwardConnection(c2, [bottomSource, leftTarget])).not.toThrow();
    });
});
