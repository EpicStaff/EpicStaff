import { NodeType } from '@shared/models';

import { ConnectionModel } from '../models/connection.model';
import { NodeModel } from '../models/node.model';
import { CustomPortId, ViewPort } from '../models/port.model';
import { buildInsertionConnections, findConnectionUnderNode } from './drop-on-connection.util';

function makePort(
    nodeId: string,
    role: string,
    portType: ViewPort['port_type'],
    position: ViewPort['position']
): ViewPort {
    return {
        id: `${nodeId}_${role}` as CustomPortId,
        port_type: portType,
        role,
        multiple: false,
        label: role,
        allowedConnections: [],
        position,
    };
}

function makeNode(
    id: string,
    type: NodeType,
    position: { x: number; y: number },
    ports: ViewPort[],
    size = { width: 200, height: 100 }
): NodeModel {
    return {
        id,
        backendId: null,
        type,
        position,
        size,
        ports,
        node_name: id,
        color: '#555',
        icon: '',
        input_map: {},
        output_variable_path: null,
        data: null,
    } as unknown as NodeModel;
}

function makeConnection(
    sourceNodeId: string,
    targetNodeId: string,
    sourcePortId: string,
    targetPortId: string
): ConnectionModel {
    return {
        id: `${sourcePortId}+${targetPortId}`,
        category: 'default',
        sourceNodeId,
        targetNodeId,
        sourcePortId: sourcePortId as CustomPortId,
        targetPortId: targetPortId as CustomPortId,
        behavior: 'fixed',
        type: 'segment',
        data: null,
    };
}

describe('findConnectionUnderNode', () => {
    it('returns the connection when its path intersects the node body', () => {
        const nodeA = makeNode('a', NodeType.AGENT, { x: 0, y: 0 }, [makePort('a', 'out', 'output', 'right')]);
        const nodeB = makeNode('b', NodeType.TASK, { x: 400, y: 0 }, [makePort('b', 'in', 'input', 'left')]);
        const connection = makeConnection('a', 'b', 'a_out', 'b_in');

        const dropped = makeNode('d', NodeType.AGENT, { x: 200, y: 0 }, [
            makePort('d', 'in', 'input', 'left'),
            makePort('d', 'out', 'output', 'right'),
        ]);

        const nodesById = new Map([nodeA, nodeB, dropped].map((n) => [n.id, n]));
        const result = findConnectionUnderNode(dropped, [connection], nodesById);
        expect(result).toBe(connection);
    });

    it('returns null when the connection path does not intersect the node body', () => {
        const nodeA = makeNode('a', NodeType.AGENT, { x: 0, y: 0 }, [makePort('a', 'out', 'output', 'right')]);
        const nodeB = makeNode('b', NodeType.TASK, { x: 400, y: 0 }, [makePort('b', 'in', 'input', 'left')]);
        const connection = makeConnection('a', 'b', 'a_out', 'b_in');

        const dropped = makeNode('d', NodeType.AGENT, { x: 200, y: 300 }, [
            makePort('d', 'in', 'input', 'left'),
            makePort('d', 'out', 'output', 'right'),
        ]);

        const nodesById = new Map([nodeA, nodeB, dropped].map((n) => [n.id, n]));
        const result = findConnectionUnderNode(dropped, [connection], nodesById);
        expect(result).toBeNull();
    });

    it('skips connections that touch the dragged node', () => {
        const nodeA = makeNode('a', NodeType.AGENT, { x: 0, y: 0 }, [makePort('a', 'out', 'output', 'right')]);
        const dropped = makeNode('d', NodeType.TASK, { x: 100, y: 0 }, [
            makePort('d', 'in', 'input', 'left'),
            makePort('d', 'out', 'output', 'right'),
        ]);
        const connection = makeConnection('a', 'd', 'a_out', 'd_in');

        const nodesById = new Map([nodeA, dropped].map((n) => [n.id, n]));
        const result = findConnectionUnderNode(dropped, [connection], nodesById);
        expect(result).toBeNull();
    });

    it('returns the first intersecting connection', () => {
        const nodeA = makeNode('a', NodeType.AGENT, { x: 0, y: 0 }, [makePort('a', 'out', 'output', 'right')]);
        const nodeB = makeNode('b', NodeType.TASK, { x: 400, y: 0 }, [makePort('b', 'in', 'input', 'left')]);
        const nodeC = makeNode('c', NodeType.TASK, { x: 400, y: 8 }, [makePort('c', 'in', 'input', 'left')]);

        const conn1 = makeConnection('a', 'b', 'a_out', 'b_in');
        const conn2 = makeConnection('a', 'c', 'a_out', 'c_in');

        const dropped = makeNode('d', NodeType.AGENT, { x: 200, y: 0 }, [
            makePort('d', 'in', 'input', 'left'),
            makePort('d', 'out', 'output', 'right'),
        ]);

        const nodesById = new Map([nodeA, nodeB, nodeC, dropped].map((n) => [n.id, n]));
        const result = findConnectionUnderNode(dropped, [conn1, conn2], nodesById);
        expect(result).toBe(conn1);
    });
});

describe('buildInsertionConnections', () => {
    it('creates two connections for a regular node', () => {
        const node = makeNode('d', NodeType.AGENT, { x: 100, y: 100 }, [
            makePort('d', 'agent-in', 'input', 'left'),
            makePort('d', 'agent-out', 'output', 'right'),
        ]);
        const connection = makeConnection('a', 'b', 'a_out', 'b_in');

        const result = buildInsertionConnections(node, connection);

        expect(result).not.toBeNull();
        expect(result!.connectionToRemove).toBe(connection);

        const [sourceToNode, nodeToTarget] = result!.newConnections;
        expect(sourceToNode.sourceNodeId).toBe('a');
        expect(sourceToNode.targetNodeId).toBe('d');
        expect(sourceToNode.sourcePortId).toBe('a_out');
        expect(sourceToNode.targetPortId).toBe('d_agent-in');

        expect(nodeToTarget.sourceNodeId).toBe('d');
        expect(nodeToTarget.targetNodeId).toBe('b');
        expect(nodeToTarget.sourcePortId).toBe('d_agent-out');
        expect(nodeToTarget.targetPortId).toBe('b_in');
    });

    it('uses decision-default port for TABLE nodes', () => {
        const node = makeNode('d', NodeType.TABLE, { x: 100, y: 100 }, [
            makePort('d', 'table-in', 'input', 'left'),
            makePort('d', 'decision-default', 'output', 'right'),
            makePort('d', 'decision-out-row1', 'output', 'right'),
        ]);
        const connection = makeConnection('a', 'b', 'a_out', 'b_in');

        const result = buildInsertionConnections(node, connection);
        expect(result).not.toBeNull();
        expect(result!.newConnections[1].sourcePortId).toBe('d_decision-default');
    });

    it('uses decision-default port for CLASSIFICATION_TABLE nodes', () => {
        const node = makeNode('d', NodeType.CLASSIFICATION_TABLE, { x: 100, y: 100 }, [
            makePort('d', 'table-in', 'input', 'left'),
            makePort('d', 'decision-default', 'output', 'right'),
            makePort('d', 'decision-route-class1', 'output', 'right'),
        ]);
        const connection = makeConnection('a', 'b', 'a_out', 'b_in');

        const result = buildInsertionConnections(node, connection);
        expect(result).not.toBeNull();
        expect(result!.newConnections[1].sourcePortId).toBe('d_decision-default');
    });

    it('returns null when node has no input port', () => {
        const node = makeNode('d', NodeType.AGENT, { x: 100, y: 100 }, [makePort('d', 'out', 'output', 'right')]);
        const connection = makeConnection('a', 'b', 'a_out', 'b_in');
        expect(buildInsertionConnections(node, connection)).toBeNull();
    });

    it('returns null when node has no output port', () => {
        const node = makeNode('d', NodeType.AGENT, { x: 100, y: 100 }, [makePort('d', 'in', 'input', 'left')]);
        const connection = makeConnection('a', 'b', 'a_out', 'b_in');
        expect(buildInsertionConnections(node, connection)).toBeNull();
    });

    it('returns null when ports array is null', () => {
        const node = makeNode('d', NodeType.AGENT, { x: 100, y: 100 }, []);
        node.ports = null;
        const connection = makeConnection('a', 'b', 'a_out', 'b_in');
        expect(buildInsertionConnections(node, connection)).toBeNull();
    });
});
