import { NodeType } from '@shared/models';

import { ConnectionModel } from '../models/connection.model';
import { NodeModel } from '../models/node.model';
import { findUnusedNodeIds } from './unused-nodes.util';

function makeNode(id: string, type: NodeType = NodeType.PYTHON): NodeModel {
    return { id, type } as unknown as NodeModel;
}

function makeConnection(sourceNodeId: string, targetNodeId: string): ConnectionModel {
    return { id: `${sourceNodeId}->${targetNodeId}`, sourceNodeId, targetNodeId } as unknown as ConnectionModel;
}

describe('findUnusedNodeIds', () => {
    it('reports a node with no connections', () => {
        const nodes = [makeNode('start', NodeType.START), makeNode('used'), makeNode('orphan')];

        expect(findUnusedNodeIds(nodes, [makeConnection('start', 'used')])).toEqual(new Set(['orphan']));
    });

    it('reports a connected chain that no entry point leads to', () => {
        const nodes = [makeNode('start', NodeType.START), makeNode('island-a'), makeNode('island-b')];

        expect(findUnusedNodeIds(nodes, [makeConnection('island-a', 'island-b')])).toEqual(
            new Set(['island-a', 'island-b'])
        );
    });

    it('treats a node that only points into the flow as unused', () => {
        const nodes = [makeNode('start', NodeType.START), makeNode('used'), makeNode('feeder')];
        const connections = [makeConnection('start', 'used'), makeConnection('feeder', 'used')];

        expect(findUnusedNodeIds(nodes, connections)).toEqual(new Set(['feeder']));
    });

    it.each([NodeType.WEBHOOK_TRIGGER, NodeType.TELEGRAM_TRIGGER, NodeType.SCHEDULE_TRIGGER])(
        'counts nodes reached from a %s trigger as used',
        (triggerType) => {
            const nodes = [makeNode('trigger', triggerType), makeNode('used')];

            expect(findUnusedNodeIds(nodes, [makeConnection('trigger', 'used')])).toEqual(new Set());
        }
    );

    it('never reports a note or an unconnected start node', () => {
        const nodes = [makeNode('start', NodeType.START), makeNode('note', NodeType.NOTE)];

        expect(findUnusedNodeIds(nodes, [])).toEqual(new Set());
    });

    it('stops on a cycle', () => {
        const nodes = [makeNode('start', NodeType.START), makeNode('first'), makeNode('second')];
        const connections = [
            makeConnection('start', 'first'),
            makeConnection('first', 'second'),
            makeConnection('second', 'first'),
        ];

        expect(findUnusedNodeIds(nodes, connections)).toEqual(new Set());
    });
});
