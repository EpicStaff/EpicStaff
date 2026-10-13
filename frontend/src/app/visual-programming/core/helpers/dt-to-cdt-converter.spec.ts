import { mapDecisionTableNodeToModel } from '../../utils/load/nodes/decision-table-node.mapper';
import { LIVE_NODE_UUID, liveDecisionTable } from '../../utils/testing/live-graph.fixture';
import { convertDecisionTableToCdt } from './dt-to-cdt-converter';

describe('convertDecisionTableToCdt', () => {
    it('gives the converted node a new uuid, since it is a new node and not the table under another type', () => {
        const decisionTableNode = mapDecisionTableNodeToModel(liveDecisionTable);
        expect(decisionTableNode.nodeUuid).toBe(LIVE_NODE_UUID.decisionTable);

        const { node } = convertDecisionTableToCdt(decisionTableNode);

        expect(node.nodeUuid).toEqual(expect.any(String));
        expect(node.nodeUuid).not.toBe(decisionTableNode.nodeUuid);
    });
});
