import { NODE_COLORS, NodeType } from '@shared/models';

import { ConnectionModel } from '../models/connection.model';
import { ConditionGroup } from '../models/decision-table.model';
import { NodeModel } from '../models/node.model';
import { generatePortsForNode, isBackwardConnection } from './helpers';

function node(
    id: string,
    x: number,
    y: number,
    width: number,
    height: number,
    portId: string,
    portPosition: string
): NodeModel {
    return {
        id,
        position: { x, y },
        size: { width, height },
        ports: [{ id: portId, position: portPosition }],
    } as unknown as NodeModel;
}

function connection(
    sourceNodeId: string,
    sourcePortId: string,
    targetNodeId: string,
    targetPortId: string
): ConnectionModel {
    return {
        id: 'conn-1',
        sourceNodeId,
        targetNodeId,
        sourcePortId,
        targetPortId,
    } as unknown as ConnectionModel;
}

describe('isBackwardConnection', () => {
    it('is false for a horizontal forward connection (source left of target)', () => {
        const source = node('source', 0, 0, 100, 60, 'source_out-right', 'right');
        const target = node('target', 300, 0, 100, 60, 'target_in-left', 'left');
        const conn = connection('source', 'source_out-right', 'target', 'target_in-left');

        expect(isBackwardConnection(conn, [source, target])).toBe(false);
    });

    it('is true for a horizontal backward connection (source exit past target entry)', () => {
        const source = node('source', 300, 0, 100, 60, 'source_out-right', 'right');
        const target = node('target', 0, 0, 100, 60, 'target_in-left', 'left');
        const conn = connection('source', 'source_out-right', 'target', 'target_in-left');

        expect(isBackwardConnection(conn, [source, target])).toBe(true);
    });

    it('is false for a vertical forward connection (source above target)', () => {
        const source = node('source', 0, 0, 100, 100, 'source_out-bottom', 'bottom');
        const target = node('target', 0, 300, 100, 100, 'target_in-top', 'top');
        const conn = connection('source', 'source_out-bottom', 'target', 'target_in-top');

        expect(isBackwardConnection(conn, [source, target])).toBe(false);
    });

    it('is true for a vertical backward connection (source exit past target entry)', () => {
        const source = node('source', 0, 300, 100, 100, 'source_out-bottom', 'bottom');
        const target = node('target', 0, 0, 100, 100, 'target_in-top', 'top');
        const conn = connection('source', 'source_out-bottom', 'target', 'target_in-top');

        expect(isBackwardConnection(conn, [source, target])).toBe(true);
    });

    it('flips from backward to forward when the target moves past the source exit edge', () => {
        const source = node('source', 300, 0, 100, 60, 'source_out-right', 'right');
        const backwardTarget = node('target', 0, 0, 100, 60, 'target_in-left', 'left');
        const conn = connection('source', 'source_out-right', 'target', 'target_in-left');

        expect(isBackwardConnection(conn, [source, backwardTarget])).toBe(true);

        const forwardTarget = node('target', 500, 0, 100, 60, 'target_in-left', 'left');

        expect(isBackwardConnection(conn, [source, forwardTarget])).toBe(false);
    });

    // A stacked pair (x-ranges overlap) wired top to bottom is a
    // sequential wire through the gap, drawn solid; wired bottom to top it stays backward (dashed).
    it('is false for a stacked pair whose target sits below the source', () => {
        const source = node('source', 0, 0, 330, 60, 'source_out-right', 'right');
        const conn = connection('source', 'source_out-right', 'target', 'target_in-left');

        for (const targetX of [0, 40, -40]) {
            const target = node('target', targetX, 120, 330, 60, 'target_in-left', 'left');

            expect(isBackwardConnection(conn, [source, target])).toBe(false);
        }
    });

    it('is true for a stacked pair whose target sits above the source', () => {
        const source = node('source', 0, 120, 330, 60, 'source_out-right', 'right');
        const target = node('target', 0, 0, 330, 60, 'target_in-left', 'left');
        const conn = connection('source', 'source_out-right', 'target', 'target_in-left');

        expect(isBackwardConnection(conn, [source, target])).toBe(true);
    });

    it('is false when either node is missing', () => {
        const source = node('source', 0, 0, 100, 60, 'source_out-right', 'right');
        const conn = connection('source', 'source_out-right', 'missing-target', 'target_in-left');

        expect(isBackwardConnection(conn, [source])).toBe(false);
    });

    it('stays true for a horizontally-backward connection regardless of the vertical gap between nodes', () => {
        const source = node('source', 600, 300, 330, 60, 'source_out-right', 'right');
        const conn = connection('source', 'source_out-right', 'target', 'target_in-left');

        for (const dy of [-200, -5, 5, 25, 40, 60, 120, 200]) {
            const target = node('target', 100, 300 + dy, 330, 60, 'target_in-left', 'left');

            expect(isBackwardConnection(conn, [source, target])).toBe(true);
        }
    });

    it('stays false for a vertically-forward connection regardless of the horizontal gap between nodes', () => {
        const source = node('source', 100, 0, 100, 60, 'source_out-bottom', 'bottom');
        const conn = connection('source', 'source_out-bottom', 'target', 'target_in-top');

        for (const dx of [5, 25, 40, 60, 120, 200]) {
            const target = node('target', 100 + dx, 200, 100, 60, 'target_in-top', 'top');

            expect(isBackwardConnection(conn, [source, target])).toBe(false);
        }
    });

    it('does not throw for mixed port orientations (falls back to layout dominance)', () => {
        const rightToTop = node('source', 0, 0, 100, 60, 'source_out-right', 'right');
        const topTarget = node('target', 300, 0, 100, 60, 'target_in-top', 'top');
        const c1 = connection('source', 'source_out-right', 'target', 'target_in-top');

        expect(() => isBackwardConnection(c1, [rightToTop, topTarget])).not.toThrow();

        const bottomSource = node('source', 0, 0, 100, 60, 'source_out-bottom', 'bottom');
        const leftTarget = node('target', 0, 300, 100, 60, 'target_in-left', 'left');
        const c2 = connection('source', 'source_out-bottom', 'target', 'target_in-left');

        expect(() => isBackwardConnection(c2, [bottomSource, leftTarget])).not.toThrow();
    });
});

function conditionGroup(groupName: string, routeCode: string): ConditionGroup {
    return {
        group_name: groupName,
        group_type: 'simple',
        expression: null,
        conditions: [],
        manipulation: null,
        next_node: null,
        route_code: routeCode,
    };
}

describe('generatePortsForNode port colors', () => {
    const tableData = { table: { condition_groups: [conditionGroup('Approved', 'APPROVE')] } };
    const nodeTypesWithPorts = Object.values(NodeType).filter((nodeType) => nodeType !== NodeType.NOTE);

    it.each(nodeTypesWithPorts)('paints every %s port in that node type colour', (nodeType) => {
        const ports = generatePortsForNode('node-1', nodeType, tableData);

        expect(ports.length).toBeGreaterThan(0);
        for (const port of ports) {
            expect({ role: port.role, color: port.color }).toEqual({ role: port.role, color: NODE_COLORS[nodeType] });
        }
    });

    it('paints the classification decision table input, route, default and error ports in its own blue', () => {
        const ports = generatePortsForNode('cdt-1', NodeType.CLASSIFICATION_TABLE, tableData);

        expect(ports.map((port) => [port.role, port.color])).toEqual([
            ['table-in', '#2a5bd7'],
            ['decision-route-APPROVE', '#2a5bd7'],
            ['decision-default', '#2a5bd7'],
            ['decision-error', '#2a5bd7'],
        ]);
    });

    it('keeps the plain decision table ports in the decision table blue', () => {
        const ports = generatePortsForNode('dt-1', NodeType.TABLE, tableData);

        expect(new Set(ports.map((port) => port.color))).toEqual(new Set(['#00aaff']));
    });
});
