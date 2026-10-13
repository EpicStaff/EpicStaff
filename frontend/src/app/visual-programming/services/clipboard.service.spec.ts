import { TestBed } from '@angular/core/testing';
import { ICurrentSelection } from '@foblex/flow';

import { mapPythonNodeToModel } from '../utils/load/nodes/python-node.mapper';
import { LIVE_NODE_UUID, livePython } from '../utils/testing/live-graph.fixture';
import { ClipboardService } from './clipboard.service';
import { FlowService } from './flow.service';

describe('ClipboardService node uuid', () => {
    let clipboard: ClipboardService;
    const sourceNode = mapPythonNodeToModel(livePython);

    beforeEach(() => {
        TestBed.inject(FlowService).setFlow({ nodes: [sourceNode], connections: [] });
        clipboard = TestBed.inject(ClipboardService);
        const selection: ICurrentSelection = { fNodeIds: [sourceNode.id], fGroupIds: [], fConnectionIds: [] };
        clipboard.copy(selection);
    });

    it('gives a pasted node a new uuid, different from its source', () => {
        expect(sourceNode.nodeUuid).toBe(LIVE_NODE_UUID.python);

        const [pasted] = clipboard.paste({ x: 100, y: 100 }).newNodes;

        expect(pasted.backendId).toBeNull();
        expect(pasted.nodeUuid).toEqual(expect.any(String));
        expect(pasted.nodeUuid).not.toBe(sourceNode.nodeUuid);
    });

    it('gives each paste of the same copy its own uuid', () => {
        const [first] = clipboard.paste({ x: 100, y: 100 }).newNodes;
        const [second] = clipboard.paste({ x: 300, y: 100 }).newNodes;

        expect(first.nodeUuid).not.toBe(second.nodeUuid);
    });
});
