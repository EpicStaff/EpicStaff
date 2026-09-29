import { NodeType } from '@shared/models';

import { ConnectionModel } from '../../core/models/connection.model';
import { FlowModel } from '../../core/models/flow.model';
import { NodeModel, StartNodeModel, SubGraphNodeModel } from '../../core/models/node.model';
import { CustomPortId } from '../../core/models/port.model';
import { extractToSubflow } from './extract-to-subflow';

function makeNode(id: string, type: NodeType, overrides: Partial<NodeModel> = {}): NodeModel {
    return {
        id,
        backendId: null,
        type,
        node_name: `node-${id}`,
        data: {} as NodeModel['data'],
        position: { x: 0, y: 0 },
        ports: null,
        color: '#000',
        icon: 'icon',
        input_map: {},
        output_variable_path: null,
        size: { width: 330, height: 60 },
        ...overrides,
    } as NodeModel;
}

function makeStartNode(id: string, overrides: Partial<StartNodeModel> = {}): StartNodeModel {
    return {
        id,
        backendId: null,
        type: NodeType.START,
        node_name: '__start__',
        data: { initialState: {} },
        position: { x: -200, y: 0 },
        ports: null,
        color: '#d3d3d3',
        icon: 'start',
        input_map: {},
        output_variable_path: null,
        size: { width: 125, height: 60 },
        ...overrides,
    };
}

function makeConnection(
    sourceNodeId: string,
    targetNodeId: string,
    sourcePortRole: string,
    targetPortRole: string
): ConnectionModel {
    const sourcePortId = `${sourceNodeId}_${sourcePortRole}` as CustomPortId;
    const targetPortId = `${targetNodeId}_${targetPortRole}` as CustomPortId;
    return {
        id: `${sourcePortId}+${targetPortId}`,
        category: 'default',
        sourceNodeId,
        targetNodeId,
        sourcePortId,
        targetPortId,
        behavior: 'fixed',
        type: 'segment',
        data: null,
    };
}

describe('extractToSubflow', () => {
    it('extracts two nodes with an internal edge into a subflow', () => {
        const start = makeStartNode('start-1');
        const nodeA = makeNode('a', NodeType.TASK, { position: { x: 100, y: 0 } });
        const nodeB = makeNode('b', NodeType.TASK, { position: { x: 300, y: 0 } });

        const startToA = makeConnection('start-1', 'a', 'start-start', 'task-in');
        const aToB = makeConnection('a', 'b', 'task-out', 'task-in');

        const parentFlow: FlowModel = {
            nodes: [start, nodeA, nodeB],
            connections: [startToA, aToB],
        };

        const result = extractToSubflow(parentFlow, new Set(['a', 'b']), 'subgraph-1', 42);

        // Subflow should have: Start + 2 cloned nodes
        expect(result.subflowModel.nodes).toHaveLength(3);
        const subflowStart = result.subflowModel.nodes.find((n) => n.type === NodeType.START);
        expect(subflowStart).toBeTruthy();

        const subflowNonStart = result.subflowModel.nodes.filter((n) => n.type !== NodeType.START);
        expect(subflowNonStart).toHaveLength(2);

        // All subflow nodes should have fresh IDs (not 'a' or 'b')
        for (const node of subflowNonStart) {
            expect(node.id).not.toBe('a');
            expect(node.id).not.toBe('b');
            expect(node.backendId).toBeNull();
        }

        // Internal edge (a→b) remapped in subflow
        const internalConnections = result.subflowModel.connections.filter((c) => c.sourceNodeId !== subflowStart!.id);
        expect(internalConnections).toHaveLength(1);

        // Start-to-entry connections: nodeA has inbound from outside (start→a),
        // so the new start wires to the clone of A. B has no external inbound
        // but has internal inbound (from A), so only A is an entry point.
        const startConnections = result.subflowModel.connections.filter((c) => c.sourceNodeId === subflowStart!.id);
        expect(startConnections).toHaveLength(1);

        // Parent should have: original Start + SubGraphNode
        expect(result.parentModel.nodes).toHaveLength(2);
        const subGraphNode = result.parentModel.nodes.find((n) => n.type === NodeType.SUBGRAPH) as SubGraphNodeModel;
        expect(subGraphNode).toBeTruthy();
        expect(subGraphNode.id).toBe('subgraph-1');
        expect(subGraphNode.data.id).toBe(42);
    });

    it('reconnects inbound edges to the SubGraphNode', () => {
        const start = makeStartNode('start-1');
        const outsideNode = makeNode('outside', NodeType.PYTHON, { position: { x: 50, y: 0 } });
        const selectedNode = makeNode('selected', NodeType.TASK, { position: { x: 200, y: 0 } });

        const startToOutside = makeConnection('start-1', 'outside', 'start-start', 'python-in');
        const outsideToSelected = makeConnection('outside', 'selected', 'python-out', 'task-in');

        const parentFlow: FlowModel = {
            nodes: [start, outsideNode, selectedNode],
            connections: [startToOutside, outsideToSelected],
        };

        const result = extractToSubflow(parentFlow, new Set(['selected']), 'sg-1', 10);

        // The inbound edge should be reconnected to the SubGraphNode's input port
        const parentConnections = result.parentModel.connections;
        const reconnectedEdge = parentConnections.find(
            (c) => c.sourceNodeId === 'outside' && c.targetNodeId === 'sg-1'
        );
        expect(reconnectedEdge).toBeTruthy();
        expect(reconnectedEdge!.targetPortId).toContain('sg-1');
        expect(reconnectedEdge!.targetPortId).toContain('subgraph-in');

        // Original inbound edge should not be in parent
        const originalEdge = parentConnections.find((c) => c.targetNodeId === 'selected');
        expect(originalEdge).toBeUndefined();
    });

    it('removes outbound edges from the parent', () => {
        const start = makeStartNode('start-1');
        const selectedNode = makeNode('selected', NodeType.TASK, { position: { x: 100, y: 0 } });
        const outsideNode = makeNode('outside', NodeType.PYTHON, { position: { x: 300, y: 0 } });

        const startToSelected = makeConnection('start-1', 'selected', 'start-start', 'task-in');
        const selectedToOutside = makeConnection('selected', 'outside', 'task-out', 'python-in');

        const parentFlow: FlowModel = {
            nodes: [start, selectedNode, outsideNode],
            connections: [startToSelected, selectedToOutside],
        };

        const result = extractToSubflow(parentFlow, new Set(['selected']), 'sg-1', 10);

        // Outbound edge (selected→outside) should not exist in parent
        const outboundEdge = result.parentModel.connections.find(
            (c) => c.sourceNodeId === 'selected' || c.targetNodeId === 'outside'
        );
        expect(outboundEdge).toBeUndefined();
    });

    it('excludes the parent Start node from selection', () => {
        const start = makeStartNode('start-1');
        const nodeA = makeNode('a', NodeType.TASK, { position: { x: 100, y: 0 } });

        const startToA = makeConnection('start-1', 'a', 'start-start', 'task-in');

        const parentFlow: FlowModel = {
            nodes: [start, nodeA],
            connections: [startToA],
        };

        // Include start-1 in selection — it should be excluded
        const result = extractToSubflow(parentFlow, new Set(['start-1', 'a']), 'sg-1', 10);

        // Start node stays in parent
        const parentStart = result.parentModel.nodes.find((n) => n.type === NodeType.START);
        expect(parentStart).toBeTruthy();
        expect(parentStart!.id).toBe('start-1');

        // Subflow has its own new Start node (not start-1)
        const subflowStart = result.subflowModel.nodes.find((n) => n.type === NodeType.START);
        expect(subflowStart).toBeTruthy();
        expect(subflowStart!.id).not.toBe('start-1');
    });

    it('handles single node extraction', () => {
        const start = makeStartNode('start-1');
        const nodeA = makeNode('a', NodeType.TASK, { position: { x: 100, y: 0 } });

        const startToA = makeConnection('start-1', 'a', 'start-start', 'task-in');

        const parentFlow: FlowModel = {
            nodes: [start, nodeA],
            connections: [startToA],
        };

        const result = extractToSubflow(parentFlow, new Set(['a']), 'sg-1', 10);

        // Subflow: Start + 1 cloned node
        expect(result.subflowModel.nodes).toHaveLength(2);

        // The single node is an entry point (inbound from outside), so start wires to it
        const subflowStart = result.subflowModel.nodes.find((n) => n.type === NodeType.START)!;
        const startConnections = result.subflowModel.connections.filter((c) => c.sourceNodeId === subflowStart.id);
        expect(startConnections).toHaveLength(1);

        // Parent: original Start + SubGraphNode
        expect(result.parentModel.nodes).toHaveLength(2);
    });

    it('uses the variable name (not the alias) as the input_map key on the SubGraphNode', () => {
        const start = makeStartNode('start-1');
        const nodeA = makeNode('a', NodeType.TASK, {
            position: { x: 100, y: 0 },
            input_map: { num: 'variables.number' },
        });

        const startToA = makeConnection('start-1', 'a', 'start-start', 'task-in');

        const parentFlow: FlowModel = {
            nodes: [start, nodeA],
            connections: [startToA],
        };

        const result = extractToSubflow(parentFlow, new Set(['a']), 'sg-1', 10);

        // Key should be 'number' (from the variable path), not 'num' (the node alias)
        expect(result.subGraphNodeInputMap).toEqual({ number: 'variables.number' });

        const subGraphNode = result.parentModel.nodes.find((n) => n.type === NodeType.SUBGRAPH) as SubGraphNodeModel;
        expect(subGraphNode.input_map).toEqual({ number: 'variables.number' });
    });

    it('excludes internal variables (produced by selected nodes) from the SubGraphNode input_map', () => {
        const start = makeStartNode('start-1');
        const nodeA = makeNode('a', NodeType.TASK, {
            position: { x: 100, y: 0 },
            input_map: { num: 'variables.number' },
            output_variable_path: 'variables.n1_res',
        });
        const nodeB = makeNode('b', NodeType.TASK, {
            position: { x: 300, y: 0 },
            input_map: { res: 'variables.n1_res' },
        });

        const startToA = makeConnection('start-1', 'a', 'start-start', 'task-in');
        const aToB = makeConnection('a', 'b', 'task-out', 'task-in');

        const parentFlow: FlowModel = {
            nodes: [start, nodeA, nodeB],
            connections: [startToA, aToB],
        };

        const result = extractToSubflow(parentFlow, new Set(['a', 'b']), 'sg-1', 10);

        // 'variables.n1_res' is produced by node A (output_variable_path), so it's internal
        // Only 'variables.number' (external) should appear on the SubGraphNode
        expect(result.subGraphNodeInputMap).toEqual({ number: 'variables.number' });
    });

    it('deduplicates input_map entries pointing to the same variable', () => {
        const start = makeStartNode('start-1');
        const nodeA = makeNode('a', NodeType.TASK, {
            position: { x: 100, y: 0 },
            input_map: { alias1: 'variables.shared_var' },
        });
        const nodeB = makeNode('b', NodeType.TASK, {
            position: { x: 300, y: 0 },
            input_map: { alias2: 'variables.shared_var' },
        });

        const parentFlow: FlowModel = {
            nodes: [start, nodeA, nodeB],
            connections: [],
        };

        const result = extractToSubflow(parentFlow, new Set(['a', 'b']), 'sg-1', 10);

        // Both reference 'variables.shared_var' → one entry keyed by 'shared_var'
        expect(result.subGraphNodeInputMap).toEqual({ shared_var: 'variables.shared_var' });
    });

    it('wires orphan selected nodes (no inbound edges) to the subflow Start', () => {
        const start = makeStartNode('start-1');
        const nodeA = makeNode('a', NodeType.TASK, { position: { x: 100, y: 0 } });
        const nodeB = makeNode('b', NodeType.TASK, { position: { x: 100, y: 100 } });

        // No connections at all — both are orphans
        const parentFlow: FlowModel = {
            nodes: [start, nodeA, nodeB],
            connections: [],
        };

        const result = extractToSubflow(parentFlow, new Set(['a', 'b']), 'sg-1', 10);

        const subflowStart = result.subflowModel.nodes.find((n) => n.type === NodeType.START)!;
        const startConnections = result.subflowModel.connections.filter((c) => c.sourceNodeId === subflowStart.id);

        // Both A and B have no inbound edges at all, so both are entry points
        expect(startConnections).toHaveLength(2);
    });

    it('positions the SubGraphNode at the centroid of selected nodes', () => {
        const start = makeStartNode('start-1');
        const nodeA = makeNode('a', NodeType.TASK, { position: { x: 100, y: 0 } });
        const nodeB = makeNode('b', NodeType.TASK, { position: { x: 300, y: 200 } });

        const parentFlow: FlowModel = {
            nodes: [start, nodeA, nodeB],
            connections: [],
        };

        const result = extractToSubflow(parentFlow, new Set(['a', 'b']), 'sg-1', 10);

        const subGraphNode = result.parentModel.nodes.find((n) => n.type === NodeType.SUBGRAPH) as SubGraphNodeModel;
        expect(subGraphNode.position.x).toBe(200);
        expect(subGraphNode.position.y).toBe(100);
    });

    it('preserves external edges in the parent', () => {
        const start = makeStartNode('start-1');
        const nodeA = makeNode('a', NodeType.TASK, { position: { x: 100, y: 0 } });
        const nodeB = makeNode('b', NodeType.PYTHON, { position: { x: 300, y: 0 } });
        const nodeC = makeNode('c', NodeType.TASK, { position: { x: 500, y: 0 } });

        const startToA = makeConnection('start-1', 'a', 'start-start', 'task-in');
        const bToC = makeConnection('b', 'c', 'python-out', 'task-in');

        const parentFlow: FlowModel = {
            nodes: [start, nodeA, nodeB, nodeC],
            connections: [startToA, bToC],
        };

        // Only select A — b→c is external
        const result = extractToSubflow(parentFlow, new Set(['a']), 'sg-1', 10);

        const externalEdge = result.parentModel.connections.find(
            (c) => c.sourceNodeId === 'b' && c.targetNodeId === 'c'
        );
        expect(externalEdge).toBeTruthy();
    });

    it('generates ports on all subflow nodes', () => {
        const start = makeStartNode('start-1');
        const nodeA = makeNode('a', NodeType.TASK, { position: { x: 100, y: 0 } });

        const parentFlow: FlowModel = {
            nodes: [start, nodeA],
            connections: [],
        };

        const result = extractToSubflow(parentFlow, new Set(['a']), 'sg-1', 10);

        for (const node of result.subflowModel.nodes) {
            expect(node.ports).toBeTruthy();
            expect(node.ports!.length).toBeGreaterThan(0);
            // Port IDs should contain the node's own ID
            for (const port of node.ports!) {
                expect(port.id).toContain(node.id);
            }
        }
    });

    it('generates ports on the SubGraphNode in the parent', () => {
        const start = makeStartNode('start-1');
        const nodeA = makeNode('a', NodeType.TASK, { position: { x: 100, y: 0 } });

        const parentFlow: FlowModel = {
            nodes: [start, nodeA],
            connections: [],
        };

        const result = extractToSubflow(parentFlow, new Set(['a']), 'sg-1', 10);

        const subGraphNode = result.parentModel.nodes.find((n) => n.type === NodeType.SUBGRAPH) as SubGraphNodeModel;
        expect(subGraphNode.ports).toBeTruthy();
        expect(subGraphNode.ports!.length).toBeGreaterThan(0);
    });
});
