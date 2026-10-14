import { mapDecisionTableNodeToModel } from '../../utils/load/nodes/decision-table-node.mapper';
import { liveDecisionTable } from '../../utils/testing/live-graph.fixture';
import { convertDecisionTableToCdt } from './dt-to-cdt-converter';

describe('convertDecisionTableToCdt execution timeout', () => {
    it('gives the new table the timeout it is handed, as a decision table runs no sandbox code to take one from', () => {
        const { node } = convertDecisionTableToCdt(mapDecisionTableNodeToModel(liveDecisionTable), 3);

        expect(node.execution_timeout).toBe(3);
    });
});
