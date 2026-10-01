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

    it('excludes internally-produced variables not in start node initial state', () => {
        const start = makeStartNode('start-1', {
            data: { initialState: { number: 0, external: '' } },
        });
        const nodeA = makeNode('a', NodeType.TASK, {
            position: { x: 100, y: 0 },
            input_map: { num: 'variables.number' },
            output_variable_path: 'variables.result',
        });
        const nodeB = makeNode('b', NodeType.TASK, {
            position: { x: 300, y: 0 },
            input_map: { res: 'variables.result', ext: 'variables.external' },
        });

        const parentFlow: FlowModel = {
            nodes: [start, nodeA, nodeB],
            connections: [makeConnection('start-1', 'a', 'start-start', 'task-in')],
        };

        const result = extractToSubflow(parentFlow, new Set(['a', 'b']), 'sg-1', 10);

        // 'result' is produced by A and not in start vars — excluded
        expect(result.subGraphNodeInputMap).toEqual({
            number: 'variables.number',
            external: 'variables.external',
        });
    });

    it('keeps internally-produced variables that exist in start node initial state', () => {
        const start = makeStartNode('start-1', {
            data: { initialState: { counter: 0, input: 'hello' } },
        });
        const nodeA = makeNode('a', NodeType.TASK, {
            position: { x: 100, y: 0 },
            input_map: { c: 'variables.counter', i: 'variables.input' },
            output_variable_path: 'variables.counter',
        });

        const parentFlow: FlowModel = {
            nodes: [start, nodeA],
            connections: [makeConnection('start-1', 'a', 'start-start', 'task-in')],
        };

        const result = extractToSubflow(parentFlow, new Set(['a']), 'sg-1', 10);

        // 'counter' is produced by A but exists in start vars — kept
        expect(result.subGraphNodeInputMap).toEqual({
            counter: 'variables.counter',
            input: 'variables.input',
        });
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

    it('does not wire disconnected nodes to the subflow Start', () => {
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

        // Neither A nor B had inbound edges from outside — they should NOT be wired to Start
        expect(startConnections).toHaveLength(0);
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

    it('remaps decision table next_node references to fresh IDs', () => {
        const start = makeStartNode('start-1');
        const dtNode = makeNode('dt', NodeType.TABLE, {
            position: { x: 100, y: 0 },
            data: {
                name: 'test-dt',
                table: {
                    default_next_node: 'target-1',
                    next_error_node: 'target-2',
                    condition_groups: [
                        {
                            group_name: 'g1',
                            next_node: 'target-1',
                            conditions: [],
                            expression: null,
                            manipulation: null,
                            group_type: 'simple',
                        },
                    ],
                },
            },
        });
        const target1 = makeNode('target-1', NodeType.TASK, { position: { x: 300, y: 0 } });
        const target2 = makeNode('target-2', NodeType.TASK, { position: { x: 300, y: 100 } });

        const parentFlow: FlowModel = {
            nodes: [start, dtNode, target1, target2],
            connections: [],
        };

        const result = extractToSubflow(parentFlow, new Set(['dt', 'target-1', 'target-2']), 'sg-1', 10);

        const subflowDt = result.subflowModel.nodes.find((n) => n.type === NodeType.TABLE)!;
        const table = (
            subflowDt.data as {
                table: {
                    default_next_node: string | null;
                    next_error_node: string | null;
                    condition_groups: Array<{ next_node: string | null }>;
                };
            }
        ).table;

        // References should be remapped to fresh IDs (not the originals)
        expect(table.default_next_node).not.toBe('target-1');
        expect(table.next_error_node).not.toBe('target-2');
        expect(table.condition_groups[0].next_node).not.toBe('target-1');

        // They should match the cloned target nodes' IDs
        const subflowTargets = result.subflowModel.nodes.filter((n) => n.type === NodeType.TASK);
        const subflowTargetIds = new Set(subflowTargets.map((n) => n.id));
        expect(subflowTargetIds.has(table.default_next_node!)).toBe(true);
        expect(subflowTargetIds.has(table.next_error_node!)).toBe(true);
        expect(subflowTargetIds.has(table.condition_groups[0].next_node!)).toBe(true);
    });

    it('redirects parent DT next_node refs from extracted nodes to the SubGraphNode', () => {
        const start = makeStartNode('start-1');
        const cdtNode = makeNode('cdt', NodeType.CLASSIFICATION_TABLE, {
            position: { x: 100, y: 0 },
            data: {
                name: 'test-cdt',
                table: {
                    default_next_node: 'extracted-node',
                    next_error_node: null,
                    condition_groups: [
                        {
                            group_name: 'g1',
                            next_node: 'extracted-node',
                            conditions: [],
                            expression: null,
                            manipulation: null,
                            group_type: 'simple',
                        },
                    ],
                },
            },
        });
        const extractedNode = makeNode('extracted-node', NodeType.TASK, { position: { x: 300, y: 0 } });

        const parentFlow: FlowModel = {
            nodes: [start, cdtNode, extractedNode],
            connections: [],
        };

        // Extract only the target node — CDT stays in parent
        const result = extractToSubflow(parentFlow, new Set(['extracted-node']), 'sg-1', 10);

        const parentCdt = result.parentModel.nodes.find((n) => n.type === NodeType.CLASSIFICATION_TABLE)!;
        const table = (
            parentCdt.data as {
                table: {
                    default_next_node: string | null;
                    condition_groups: Array<{ next_node: string | null }>;
                };
            }
        ).table;

        // References should now point to the SubGraphNode, not the extracted node
        expect(table.default_next_node).toBe('sg-1');
        expect(table.condition_groups[0].next_node).toBe('sg-1');
    });

    it('nulls decision table references to nodes outside the selection', () => {
        const start = makeStartNode('start-1');
        const dtNode = makeNode('dt', NodeType.TABLE, {
            position: { x: 100, y: 0 },
            data: {
                name: 'test-dt',
                table: {
                    default_next_node: 'outside-node',
                    next_error_node: null,
                    condition_groups: [],
                },
            },
        });
        const outsideNode = makeNode('outside-node', NodeType.TASK, { position: { x: 300, y: 0 } });

        const parentFlow: FlowModel = {
            nodes: [start, dtNode, outsideNode],
            connections: [],
        };

        // Only extract dt, not outside-node
        const result = extractToSubflow(parentFlow, new Set(['dt']), 'sg-1', 10);

        const subflowDt = result.subflowModel.nodes.find((n) => n.type === NodeType.TABLE)!;
        const table = (subflowDt.data as { table: { default_next_node: string | null } }).table;

        // Reference to outside-node should be nulled since it's not in the selection
        expect(table.default_next_node).toBeNull();
    });

    it('collects CDT expression/manipulation variable refs into SubGraphNode input_map', () => {
        const start = makeStartNode('start-1');
        const cdtNode = makeNode('cdt', NodeType.CLASSIFICATION_TABLE, {
            position: { x: 100, y: 0 },
            data: {
                name: 'test-cdt',
                table: {
                    default_next_node: null,
                    next_error_node: null,
                    condition_groups: [
                        {
                            group_name: 'g1',
                            next_node: null,
                            conditions: [],
                            expression: 'variables.status == "active" and variables.count > 0',
                            manipulation: 'variables.result = variables.score + 1',
                            group_type: 'simple',
                        },
                    ],
                },
            },
        });

        const parentFlow: FlowModel = {
            nodes: [start, cdtNode],
            connections: [],
        };

        const result = extractToSubflow(parentFlow, new Set(['cdt']), 'sg-1', 10);

        // All external variables from expressions/manipulations should appear
        expect(result.subGraphNodeInputMap['status']).toBe('variables.status');
        expect(result.subGraphNodeInputMap['count']).toBe('variables.count');
        expect(result.subGraphNodeInputMap['result']).toBe('variables.result');
        expect(result.subGraphNodeInputMap['score']).toBe('variables.score');
    });

    it('collects CDT field_expressions/field_manipulations keys into SubGraphNode input_map', () => {
        const start = makeStartNode('start-1');
        const cdtNode = makeNode('cdt', NodeType.CLASSIFICATION_TABLE, {
            position: { x: 100, y: 0 },
            data: {
                name: 'test-cdt',
                table: {
                    default_next_node: null,
                    next_error_node: null,
                    condition_groups: [
                        {
                            group_name: 'g1',
                            next_node: null,
                            conditions: [],
                            expression: null,
                            manipulation: null,
                            group_type: 'simple',
                            field_expressions: { age: '> 18', name: '"John"' },
                            field_manipulations: { total: 'total + 1' },
                        },
                    ],
                },
            },
        });

        const parentFlow: FlowModel = {
            nodes: [start, cdtNode],
            connections: [],
        };

        const result = extractToSubflow(parentFlow, new Set(['cdt']), 'sg-1', 10);

        expect(result.subGraphNodeInputMap['age']).toBe('variables.age');
        expect(result.subGraphNodeInputMap['name']).toBe('variables.name');
        expect(result.subGraphNodeInputMap['total']).toBe('variables.total');
    });

    it('collects CDT pre/post input_map variables into SubGraphNode input_map', () => {
        const start = makeStartNode('start-1');
        const cdtNode = makeNode('cdt', NodeType.CLASSIFICATION_TABLE, {
            position: { x: 100, y: 0 },
            data: {
                name: 'test-cdt',
                table: {
                    default_next_node: null,
                    next_error_node: null,
                    pre_input_map: { local_id: 'variables.user_id' },
                    post_input_map: { local_score: 'variables.final_score' },
                    condition_groups: [],
                },
            },
        });

        const parentFlow: FlowModel = {
            nodes: [start, cdtNode],
            connections: [],
        };

        const result = extractToSubflow(parentFlow, new Set(['cdt']), 'sg-1', 10);

        expect(result.subGraphNodeInputMap['user_id']).toBe('variables.user_id');
        expect(result.subGraphNodeInputMap['final_score']).toBe('variables.final_score');
    });

    it('reads CDT pre_computation.input_map when legacy pre_input_map is empty', () => {
        const start = makeStartNode('start-1');
        const cdtNode = makeNode('cdt', NodeType.CLASSIFICATION_TABLE, {
            position: { x: 100, y: 0 },
            data: {
                name: 'test-cdt',
                table: {
                    default_next_node: null,
                    next_error_node: null,
                    pre_computation: {
                        code: '',
                        input_map: { local_id: 'variables.user_id' },
                        output_variable_path: null,
                    },
                    post_computation: {
                        code: '',
                        input_map: { local_score: 'variables.final_score' },
                        output_variable_path: null,
                    },
                    condition_groups: [],
                },
            },
        });

        const parentFlow: FlowModel = {
            nodes: [start, cdtNode],
            connections: [],
        };

        const result = extractToSubflow(parentFlow, new Set(['cdt']), 'sg-1', 10);

        expect(result.subGraphNodeInputMap['user_id']).toBe('variables.user_id');
        expect(result.subGraphNodeInputMap['final_score']).toBe('variables.final_score');
    });

    it('excludes CDT pre/post computation output_variable_path from SubGraphNode input_map', () => {
        const start = makeStartNode('start-1');
        const cdtNode = makeNode('cdt', NodeType.CLASSIFICATION_TABLE, {
            position: { x: 100, y: 0 },
            data: {
                name: 'test-cdt',
                table: {
                    default_next_node: null,
                    next_error_node: null,
                    pre_computation: {
                        code: '',
                        input_map: {},
                        output_variable_path: 'variables.pre_result',
                    },
                    post_computation: {
                        code: '',
                        input_map: {},
                        output_variable_path: 'variables.post_result',
                    },
                    condition_groups: [
                        {
                            group_name: 'g1',
                            next_node: null,
                            conditions: [],
                            expression: 'variables.pre_result > 0 and variables.post_result > 0 and variables.external',
                            manipulation: null,
                            group_type: 'simple',
                        },
                    ],
                },
            },
        });

        const parentFlow: FlowModel = {
            nodes: [start, cdtNode],
            connections: [],
        };

        const result = extractToSubflow(parentFlow, new Set(['cdt']), 'sg-1', 10);

        // pre_result and post_result are produced by the CDT's own computations — excluded
        expect(result.subGraphNodeInputMap['pre_result']).toBeUndefined();
        expect(result.subGraphNodeInputMap['post_result']).toBeUndefined();
        // external is not produced internally — included
        expect(result.subGraphNodeInputMap['external']).toBe('variables.external');
    });

    it('excludes internal CDT variable refs produced by nodes in the selection', () => {
        const start = makeStartNode('start-1');
        const producer = makeNode('producer', NodeType.PYTHON, {
            position: { x: 100, y: 0 },
            output_variable_path: 'variables.internal_result',
        });
        const cdtNode = makeNode('cdt', NodeType.CLASSIFICATION_TABLE, {
            position: { x: 300, y: 0 },
            data: {
                name: 'test-cdt',
                table: {
                    default_next_node: null,
                    next_error_node: null,
                    condition_groups: [
                        {
                            group_name: 'g1',
                            next_node: null,
                            conditions: [],
                            expression: 'variables.internal_result > 0 and variables.external_flag',
                            manipulation: null,
                            group_type: 'simple',
                            field_expressions: { internal_result: '> 0' },
                        },
                    ],
                },
            },
        });

        const parentFlow: FlowModel = {
            nodes: [start, producer, cdtNode],
            connections: [],
        };

        const result = extractToSubflow(parentFlow, new Set(['producer', 'cdt']), 'sg-1', 10);

        // internal_result is produced by 'producer' and not in start vars — excluded
        expect(result.subGraphNodeInputMap['internal_result']).toBeUndefined();
        // external_flag is not produced internally — included
        expect(result.subGraphNodeInputMap['external_flag']).toBe('variables.external_flag');
    });
});
