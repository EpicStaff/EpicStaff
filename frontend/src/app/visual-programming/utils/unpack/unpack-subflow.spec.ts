import { NodeType } from '@shared/models';

import { ConnectionModel } from '../../core/models/connection.model';
import { FlowModel } from '../../core/models/flow.model';
import { EndNodeModel, NodeModel, StartNodeModel, SubGraphNodeModel } from '../../core/models/node.model';
import { CustomPortId } from '../../core/models/port.model';
import { unpackSubflow } from './unpack-subflow';

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

function makeEndNode(id: string, overrides: Partial<EndNodeModel> = {}): EndNodeModel {
    return {
        id,
        backendId: null,
        type: NodeType.END,
        node_name: '__end__',
        data: { output_map: {} },
        position: { x: 500, y: 0 },
        ports: null,
        color: '#d3d3d3',
        icon: 'end',
        input_map: {},
        output_variable_path: null,
        size: { width: 125, height: 60 },
        ...overrides,
    };
}

function makeSubGraphNode(id: string, overrides: Partial<SubGraphNodeModel> = {}): SubGraphNodeModel {
    return {
        id,
        backendId: null,
        type: NodeType.SUBGRAPH,
        node_name: 'My Subflow',
        data: { id: 42, uuid: 'abc', name: 'subflow', description: '' },
        position: { x: 200, y: 0 },
        ports: null,
        color: '#000',
        icon: 'subgraph',
        input_map: {},
        output_variable_path: null,
        size: { width: 330, height: 60 },
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

describe('unpackSubflow', () => {
    it('inlines subflow nodes into parent and removes the SubGraphNode', () => {
        const parentStart = makeStartNode('parent-start');
        const subGraphNode = makeSubGraphNode('sg-1');
        const startToSg = makeConnection('parent-start', 'sg-1', 'start-start', 'subgraph-in');

        const parentFlow: FlowModel = {
            nodes: [parentStart, subGraphNode],
            connections: [startToSg],
        };

        const subStart = makeStartNode('sub-start');
        const subEnd = makeEndNode('sub-end');
        const taskA = makeNode('task-a', NodeType.TASK, { position: { x: 100, y: 0 } });
        const taskB = makeNode('task-b', NodeType.TASK, { position: { x: 300, y: 0 } });
        const startToA = makeConnection('sub-start', 'task-a', 'start-start', 'task-in');
        const aToB = makeConnection('task-a', 'task-b', 'task-out', 'task-in');
        const bToEnd = makeConnection('task-b', 'sub-end', 'task-out', 'end-in');

        const subflowModel: FlowModel = {
            nodes: [subStart, taskA, taskB, subEnd],
            connections: [startToA, aToB, bToEnd],
        };

        const result = unpackSubflow(parentFlow, 'sg-1', subflowModel);

        // SubGraphNode should be removed
        expect(result.nodes.find((node) => node.id === 'sg-1')).toBeUndefined();

        // Parent start remains
        expect(result.nodes.find((node) => node.id === 'parent-start')).toBeTruthy();

        // Two inlined nodes (task-a, task-b clones)
        const inlinedNodes = result.nodes.filter((node) => node.type === NodeType.TASK);
        expect(inlinedNodes).toHaveLength(2);
    });

    it('filters out the subflow Start and End nodes', () => {
        const parentStart = makeStartNode('parent-start');
        const subGraphNode = makeSubGraphNode('sg-1');
        const startToSg = makeConnection('parent-start', 'sg-1', 'start-start', 'subgraph-in');

        const parentFlow: FlowModel = {
            nodes: [parentStart, subGraphNode],
            connections: [startToSg],
        };

        const subStart = makeStartNode('sub-start');
        const subEnd = makeEndNode('sub-end');
        const taskA = makeNode('task-a', NodeType.TASK, { position: { x: 100, y: 0 } });
        const startToA = makeConnection('sub-start', 'task-a', 'start-start', 'task-in');
        const aToEnd = makeConnection('task-a', 'sub-end', 'task-out', 'end-in');

        const subflowModel: FlowModel = {
            nodes: [subStart, taskA, subEnd],
            connections: [startToA, aToEnd],
        };

        const result = unpackSubflow(parentFlow, 'sg-1', subflowModel);

        // No Start or End from the subflow should appear
        const startNodes = result.nodes.filter((node) => node.type === NodeType.START);
        expect(startNodes).toHaveLength(1); // only parent start
        expect(startNodes[0].id).toBe('parent-start');

        const endNodes = result.nodes.filter((node) => node.type === NodeType.END);
        expect(endNodes).toHaveLength(0);
    });

    it('resolves name conflicts by appending (2), (3), etc.', () => {
        const parentStart = makeStartNode('parent-start');
        const existingTask = makeNode('existing', NodeType.TASK, { node_name: 'My Task' });
        const subGraphNode = makeSubGraphNode('sg-1');

        const parentFlow: FlowModel = {
            nodes: [parentStart, existingTask, subGraphNode],
            connections: [],
        };

        const subStart = makeStartNode('sub-start');
        const conflictingTask = makeNode('conflict-task', NodeType.TASK, {
            node_name: 'My Task',
            position: { x: 100, y: 0 },
        });
        const startToConflict = makeConnection('sub-start', 'conflict-task', 'start-start', 'task-in');

        const subflowModel: FlowModel = {
            nodes: [subStart, conflictingTask],
            connections: [startToConflict],
        };

        const result = unpackSubflow(parentFlow, 'sg-1', subflowModel);

        const taskNames = result.nodes.filter((node) => node.type === NodeType.TASK).map((node) => node.node_name);
        expect(taskNames).toContain('My Task');
        expect(taskNames).toContain('My Task (2)');
    });

    it('rewires inbound edges to entry-point nodes', () => {
        const parentStart = makeStartNode('parent-start');
        const outsideNode = makeNode('outside', NodeType.PYTHON, { position: { x: 50, y: 0 } });
        const subGraphNode = makeSubGraphNode('sg-1');
        const startToOutside = makeConnection('parent-start', 'outside', 'start-start', 'python-in');
        const outsideToSg = makeConnection('outside', 'sg-1', 'python-out', 'subgraph-in');

        const parentFlow: FlowModel = {
            nodes: [parentStart, outsideNode, subGraphNode],
            connections: [startToOutside, outsideToSg],
        };

        const subStart = makeStartNode('sub-start');
        const taskA = makeNode('task-a', NodeType.TASK, { position: { x: 100, y: 0 } });
        const startToA = makeConnection('sub-start', 'task-a', 'start-start', 'task-in');

        const subflowModel: FlowModel = {
            nodes: [subStart, taskA],
            connections: [startToA],
        };

        const result = unpackSubflow(parentFlow, 'sg-1', subflowModel);

        // The edge from outside should now point to the inlined task node
        const inlinedTask = result.nodes.find((node) => node.type === NodeType.TASK && node.id !== 'existing')!;
        const rewiredEdge = result.connections.find(
            (connection) => connection.sourceNodeId === 'outside' && connection.targetNodeId === inlinedTask.id
        );
        expect(rewiredEdge).toBeTruthy();
        expect(rewiredEdge!.targetPortId).toContain(inlinedTask.id);

        // No edge should reference sg-1 anymore
        const sgEdges = result.connections.filter(
            (connection) => connection.sourceNodeId === 'sg-1' || connection.targetNodeId === 'sg-1'
        );
        expect(sgEdges).toHaveLength(0);
    });

    it('merges SubGraphNode input_map into entry-point nodes', () => {
        const parentStart = makeStartNode('parent-start');
        const subGraphNode = makeSubGraphNode('sg-1', {
            input_map: { parentKey: 'parentValue', sharedKey: 'fromParent' },
        });
        const startToSg = makeConnection('parent-start', 'sg-1', 'start-start', 'subgraph-in');

        const parentFlow: FlowModel = {
            nodes: [parentStart, subGraphNode],
            connections: [startToSg],
        };

        const subStart = makeStartNode('sub-start');
        const taskA = makeNode('task-a', NodeType.TASK, {
            position: { x: 100, y: 0 },
            input_map: { taskKey: 'taskValue', sharedKey: 'fromTask' },
        });
        const startToA = makeConnection('sub-start', 'task-a', 'start-start', 'task-in');

        const subflowModel: FlowModel = {
            nodes: [subStart, taskA],
            connections: [startToA],
        };

        const result = unpackSubflow(parentFlow, 'sg-1', subflowModel);

        const inlinedTask = result.nodes.find((node) => node.type === NodeType.TASK)!;
        // parentKey should be merged in
        expect(inlinedTask.input_map['parentKey']).toBe('parentValue');
        // taskKey should remain
        expect(inlinedTask.input_map['taskKey']).toBe('taskValue');
        // sharedKey already existed on the task, so it should NOT be overwritten
        expect(inlinedTask.input_map['sharedKey']).toBe('fromTask');
    });

    it('skips merging input_map entries whose value already exists under a different key', () => {
        const parentStart = makeStartNode('parent-start');
        const subGraphNode = makeSubGraphNode('sg-1', {
            input_map: { number: 'variables.number' },
        });
        const startToSg = makeConnection('parent-start', 'sg-1', 'start-start', 'subgraph-in');

        const parentFlow: FlowModel = {
            nodes: [parentStart, subGraphNode],
            connections: [startToSg],
        };

        const subStart = makeStartNode('sub-start');
        const taskA = makeNode('task-a', NodeType.TASK, {
            position: { x: 100, y: 0 },
            input_map: { num: 'variables.number' },
        });
        const startToA = makeConnection('sub-start', 'task-a', 'start-start', 'task-in');

        const subflowModel: FlowModel = {
            nodes: [subStart, taskA],
            connections: [startToA],
        };

        const result = unpackSubflow(parentFlow, 'sg-1', subflowModel);

        const inlinedTask = result.nodes.find((node) => node.type === NodeType.TASK)!;
        // Node already maps 'variables.number' under alias 'num' — should NOT add 'number' key
        expect(inlinedTask.input_map).toEqual({ num: 'variables.number' });
    });

    it('keeps nested SubGraphNodes as-is (no recursive inlining)', () => {
        const parentStart = makeStartNode('parent-start');
        const subGraphNode = makeSubGraphNode('sg-1');
        const startToSg = makeConnection('parent-start', 'sg-1', 'start-start', 'subgraph-in');

        const parentFlow: FlowModel = {
            nodes: [parentStart, subGraphNode],
            connections: [startToSg],
        };

        const subStart = makeStartNode('sub-start');
        const nestedSubGraph = makeSubGraphNode('nested-sg', {
            node_name: 'Nested Subflow',
            data: { id: 99, uuid: 'nested', name: 'nested', description: '' },
        });
        const startToNested = makeConnection('sub-start', 'nested-sg', 'start-start', 'subgraph-in');

        const subflowModel: FlowModel = {
            nodes: [subStart, nestedSubGraph],
            connections: [startToNested],
        };

        const result = unpackSubflow(parentFlow, 'sg-1', subflowModel);

        const subgraphNodes = result.nodes.filter((node) => node.type === NodeType.SUBGRAPH);
        // The original sg-1 is removed, but the nested one should be inlined (with new ID)
        expect(subgraphNodes).toHaveLength(1);
        expect(subgraphNodes[0].id).not.toBe('sg-1');
        expect(subgraphNodes[0].id).not.toBe('nested-sg');
        expect(subgraphNodes[0].node_name).toBe('Nested Subflow');
    });

    it('assigns fresh UUIDs and null backendIds to all inlined nodes', () => {
        const parentStart = makeStartNode('parent-start');
        const subGraphNode = makeSubGraphNode('sg-1');

        const parentFlow: FlowModel = {
            nodes: [parentStart, subGraphNode],
            connections: [],
        };

        const subStart = makeStartNode('sub-start');
        const taskA = makeNode('task-a', NodeType.TASK, {
            backendId: 123,
            position: { x: 100, y: 0 },
        });
        const taskB = makeNode('task-b', NodeType.TASK, {
            backendId: 456,
            position: { x: 300, y: 0 },
        });
        const startToA = makeConnection('sub-start', 'task-a', 'start-start', 'task-in');

        const subflowModel: FlowModel = {
            nodes: [subStart, taskA, taskB],
            connections: [startToA],
        };

        const result = unpackSubflow(parentFlow, 'sg-1', subflowModel);

        const inlinedNodes = result.nodes.filter((node) => node.type === NodeType.TASK);
        expect(inlinedNodes).toHaveLength(2);
        for (const node of inlinedNodes) {
            expect(node.id).not.toBe('task-a');
            expect(node.id).not.toBe('task-b');
            expect(node.backendId).toBeNull();
        }
    });

    it('fans out inbound edges to multiple entry points', () => {
        const parentStart = makeStartNode('parent-start');
        const outsideNode = makeNode('outside', NodeType.PYTHON, { position: { x: 50, y: 0 } });
        const subGraphNode = makeSubGraphNode('sg-1');
        const outsideToSg = makeConnection('outside', 'sg-1', 'python-out', 'subgraph-in');

        const parentFlow: FlowModel = {
            nodes: [parentStart, outsideNode, subGraphNode],
            connections: [outsideToSg],
        };

        const subStart = makeStartNode('sub-start');
        const taskA = makeNode('task-a', NodeType.TASK, { position: { x: 100, y: 0 } });
        const taskB = makeNode('task-b', NodeType.TASK, {
            node_name: 'node-task-b',
            position: { x: 100, y: 100 },
        });
        const startToA = makeConnection('sub-start', 'task-a', 'start-start', 'task-in');
        const startToB = makeConnection('sub-start', 'task-b', 'start-start', 'task-in');

        const subflowModel: FlowModel = {
            nodes: [subStart, taskA, taskB],
            connections: [startToA, startToB],
        };

        const result = unpackSubflow(parentFlow, 'sg-1', subflowModel);

        // The single inbound edge should fan out to both entry-point nodes
        const rewiredEdges = result.connections.filter((connection) => connection.sourceNodeId === 'outside');
        expect(rewiredEdges).toHaveLength(2);

        const targetIds = new Set(rewiredEdges.map((connection) => connection.targetNodeId));
        const inlinedTasks = result.nodes.filter((node) => node.type === NodeType.TASK);
        for (const task of inlinedTasks) {
            expect(targetIds.has(task.id)).toBe(true);
        }
    });

    it('removes outbound edges from SubGraphNode without rewiring', () => {
        const parentStart = makeStartNode('parent-start');
        const subGraphNode = makeSubGraphNode('sg-1');
        const downstreamNode = makeNode('downstream', NodeType.PYTHON, { position: { x: 400, y: 0 } });
        const startToSg = makeConnection('parent-start', 'sg-1', 'start-start', 'subgraph-in');
        const sgToDownstream = makeConnection('sg-1', 'downstream', 'subgraph-out', 'python-in');

        const parentFlow: FlowModel = {
            nodes: [parentStart, subGraphNode, downstreamNode],
            connections: [startToSg, sgToDownstream],
        };

        const subStart = makeStartNode('sub-start');
        const taskA = makeNode('task-a', NodeType.TASK, { position: { x: 100, y: 0 } });
        const startToA = makeConnection('sub-start', 'task-a', 'start-start', 'task-in');

        const subflowModel: FlowModel = {
            nodes: [subStart, taskA],
            connections: [startToA],
        };

        const result = unpackSubflow(parentFlow, 'sg-1', subflowModel);

        // The outbound edge (sg-1 -> downstream) should be removed entirely
        const edgesToDownstream = result.connections.filter((connection) => connection.targetNodeId === 'downstream');
        expect(edgesToDownstream).toHaveLength(0);

        // downstream node itself should still exist
        expect(result.nodes.find((node) => node.id === 'downstream')).toBeTruthy();
    });

    it('throws when the SubGraphNode is not found', () => {
        const parentFlow: FlowModel = {
            nodes: [makeStartNode('parent-start')],
            connections: [],
        };

        const subflowModel: FlowModel = { nodes: [], connections: [] };

        expect(() => unpackSubflow(parentFlow, 'nonexistent', subflowModel)).toThrow(/not found in parent flow/);
    });

    it('generates ports on all inlined nodes', () => {
        const parentStart = makeStartNode('parent-start');
        const subGraphNode = makeSubGraphNode('sg-1');

        const parentFlow: FlowModel = {
            nodes: [parentStart, subGraphNode],
            connections: [],
        };

        const subStart = makeStartNode('sub-start');
        const taskA = makeNode('task-a', NodeType.TASK, { position: { x: 100, y: 0 } });
        const startToA = makeConnection('sub-start', 'task-a', 'start-start', 'task-in');

        const subflowModel: FlowModel = {
            nodes: [subStart, taskA],
            connections: [startToA],
        };

        const result = unpackSubflow(parentFlow, 'sg-1', subflowModel);

        const inlinedTask = result.nodes.find((node) => node.type === NodeType.TASK)!;
        expect(inlinedTask.ports).toBeTruthy();
        expect(inlinedTask.ports!.length).toBeGreaterThan(0);
        for (const port of inlinedTask.ports!) {
            expect(port.id).toContain(inlinedTask.id);
        }
    });

    it('copies internal subflow edges with remapped IDs', () => {
        const parentStart = makeStartNode('parent-start');
        const subGraphNode = makeSubGraphNode('sg-1');
        const startToSg = makeConnection('parent-start', 'sg-1', 'start-start', 'subgraph-in');

        const parentFlow: FlowModel = {
            nodes: [parentStart, subGraphNode],
            connections: [startToSg],
        };

        const subStart = makeStartNode('sub-start');
        const taskA = makeNode('task-a', NodeType.TASK, { position: { x: 100, y: 0 } });
        const taskB = makeNode('task-b', NodeType.TASK, { position: { x: 300, y: 0 } });
        const startToA = makeConnection('sub-start', 'task-a', 'start-start', 'task-in');
        const aToB = makeConnection('task-a', 'task-b', 'task-out', 'task-in');

        const subflowModel: FlowModel = {
            nodes: [subStart, taskA, taskB],
            connections: [startToA, aToB],
        };

        const result = unpackSubflow(parentFlow, 'sg-1', subflowModel);

        const inlinedTasks = result.nodes.filter((node) => node.type === NodeType.TASK);
        expect(inlinedTasks).toHaveLength(2);

        // The internal edge (taskA -> taskB) should be remapped
        const internalEdge = result.connections.find(
            (connection) =>
                inlinedTasks.some((node) => node.id === connection.sourceNodeId) &&
                inlinedTasks.some((node) => node.id === connection.targetNodeId)
        );
        expect(internalEdge).toBeTruthy();
        expect(internalEdge!.sourceNodeId).not.toBe('task-a');
        expect(internalEdge!.targetNodeId).not.toBe('task-b');
    });

    it('handles name conflicts with incrementing suffixes', () => {
        const parentStart = makeStartNode('parent-start');
        const existingTask1 = makeNode('existing-1', NodeType.TASK, { node_name: 'Duplicate' });
        const existingTask2 = makeNode('existing-2', NodeType.PYTHON, { node_name: 'Duplicate (2)' });
        const subGraphNode = makeSubGraphNode('sg-1');

        const parentFlow: FlowModel = {
            nodes: [parentStart, existingTask1, existingTask2, subGraphNode],
            connections: [],
        };

        const subStart = makeStartNode('sub-start');
        const conflictTask = makeNode('conflict', NodeType.TASK, {
            node_name: 'Duplicate',
            position: { x: 100, y: 0 },
        });
        const startToConflict = makeConnection('sub-start', 'conflict', 'start-start', 'task-in');

        const subflowModel: FlowModel = {
            nodes: [subStart, conflictTask],
            connections: [startToConflict],
        };

        const result = unpackSubflow(parentFlow, 'sg-1', subflowModel);

        const inlinedTask = result.nodes.find((node) => node.type === NodeType.TASK && node.id !== 'existing-1')!;
        // "Duplicate" and "Duplicate (2)" are taken, so it should get "Duplicate (3)"
        expect(inlinedTask.node_name).toBe('Duplicate (3)');
    });
});
