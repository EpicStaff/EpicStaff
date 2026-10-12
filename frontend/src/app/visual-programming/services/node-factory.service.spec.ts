import { TestBed } from '@angular/core/testing';
import { NodeType } from '@shared/models';

import { NodeFactoryService } from './node-factory.service';

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
