import { NodeType } from '@shared/models';

import { FlowModel } from '../../core/models/flow.model';
import { NodeModel } from '../../core/models/node.model';
import { mapGraphDtoToFlowModel } from '../load/map-graph-dto-to-flow-model';
import { liveGraph } from '../testing/live-graph.fixture';
import { getNodeDiff } from './diff';
import { hasTriggerNodeWrites } from './trigger-node-writes';

// One saved node of every type, the trigger nodes included.
const saved: FlowModel = mapGraphDtoToFlowModel(liveGraph);

function nodeOf(type: NodeType): NodeModel {
    return saved.nodes.find((node) => node.type === type)!;
}

function withNodes(nodes: NodeModel[]): FlowModel {
    return { ...saved, nodes };
}

function renamed(target: NodeModel): FlowModel {
    return withNodes(
        saved.nodes.map((node) => (node === target ? { ...node, node_name: `${node.node_name} renamed` } : node))
    );
}

function writesTriggers(current: FlowModel): boolean {
    return hasTriggerNodeWrites(getNodeDiff(saved, current));
}

describe('hasTriggerNodeWrites', () => {
    const triggerTypes = [NodeType.WEBHOOK_TRIGGER, NodeType.TELEGRAM_TRIGGER, NodeType.SCHEDULE_TRIGGER];

    it('is false for an unchanged flow', () => {
        expect(writesTriggers(saved)).toBe(false);
    });

    it.each(triggerTypes)('is true when a %s node changes', (type) => {
        expect(writesTriggers(renamed(nodeOf(type)))).toBe(true);
    });

    it.each(triggerTypes)('is true when a %s node is created', (type) => {
        const created = { ...nodeOf(type), id: 'new-trigger', backendId: null } as NodeModel;

        expect(writesTriggers(withNodes([...saved.nodes, created]))).toBe(true);
    });

    it.each(triggerTypes)('is false when a %s node is only deleted', (type) => {
        const deleted = nodeOf(type);

        expect(writesTriggers(withNodes(saved.nodes.filter((node) => node !== deleted)))).toBe(false);
    });

    it('is false when only other nodes are created or changed', () => {
        const createdPython = { ...nodeOf(NodeType.PYTHON), id: 'new-python', backendId: null } as NodeModel;
        const changed = renamed(nodeOf(NodeType.PYTHON));

        expect(writesTriggers(withNodes([...changed.nodes, createdPython]))).toBe(false);
    });
});
