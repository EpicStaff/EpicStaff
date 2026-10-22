import { TestBed } from '@angular/core/testing';
import { NodeType } from '@shared/models';

import { NodeModel } from '../core/models/node.model';
import { FlowService } from './flow.service';
import { NodeFactoryService } from './node-factory.service';

describe('NodeFactoryService', () => {
    let factory: NodeFactoryService;

    beforeEach(() => {
        const flowService = TestBed.inject(FlowService);
        flowService.setFlow({
            nodes: [
                {
                    id: 'existing',
                    type: NodeType.PYTHON,
                    nodeNumber: 4,
                    position: { x: 900, y: 900 },
                    size: { width: 200, height: 100 },
                } as NodeModel,
            ],
            connections: [],
        });
        flowService.setNodeNumberFloor(4);
        factory = TestBed.inject(NodeFactoryService);
    });

    it('names a new node after its type and keeps the next number out of the name', () => {
        const created = factory.createNode(NodeType.PYTHON);

        expect(created.node_name).toBe('Python-Node');
        expect(created.nodeNumber).toBe(5);
    });

    it.each([NodeType.NOTE, NodeType.START, NodeType.END])('gives a new %s node no number', (type) => {
        expect(factory.createNode(type).nodeNumber).toBeUndefined();
    });

    it('does not use up a number on an unnumbered node', () => {
        factory.createNode(NodeType.NOTE);

        expect(factory.createNode(NodeType.TASK).nodeNumber).toBe(5);
    });
});

describe('NodeFactoryService node uuid', () => {
    let factory: NodeFactoryService;

    beforeEach(() => {
        factory = TestBed.inject(NodeFactoryService);
    });

    it('gives every created node its own uuid', () => {
        const first = factory.createNode(NodeType.PYTHON);
        const second = factory.createNode(NodeType.PYTHON);

        expect(first.nodeUuid).toEqual(expect.any(String));
        expect(second.nodeUuid).toEqual(expect.any(String));
        expect(first.nodeUuid).not.toBe(second.nodeUuid);
        expect(first.nodeUuid).not.toBe(first.id);
    });

    it('gives a new uuid even when the overrides carry one', () => {
        const node = factory.createNode(NodeType.NOTE, { nodeUuid: 'copied-node-uuid' });

        expect(node.nodeUuid).toEqual(expect.any(String));
        expect(node.nodeUuid).not.toBe('copied-node-uuid');
    });
});
