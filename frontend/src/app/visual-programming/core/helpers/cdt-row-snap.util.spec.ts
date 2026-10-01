import { NodeType } from '@shared/models';

import { ConnectionModel } from '../models/connection.model';
import { NodeModel } from '../models/node.model';
import { CustomPortId, ViewPort } from '../models/port.model';
import { computeRowSnapY } from './cdt-row-snap.util';

function port(nodeId: string, role: string, position: ViewPort['position'] = 'right'): ViewPort {
    return {
        id: `${nodeId}_${role}` as CustomPortId,
        port_type: 'output',
        role,
        multiple: true,
        label: role,
        allowedConnections: [],
        position,
    };
}

function makeNode(
    id: string,
    type: NodeType,
    opts: { y?: number; height?: number; data?: unknown; ports?: ViewPort[] } = {}
): NodeModel {
    return {
        id,
        type,
        position: { x: 0, y: opts.y ?? 0 },
        size: { width: 330, height: opts.height ?? 60 },
        ports: opts.ports ?? [],
        data: opts.data ?? null,
    } as unknown as NodeModel;
}

function conn(id: string, sourceId: string, sourceRole: string, targetId: string): ConnectionModel {
    return {
        id,
        category: 'default',
        sourceNodeId: sourceId,
        targetNodeId: targetId,
        sourcePortId: `${sourceId}_${sourceRole}` as CustomPortId,
        targetPortId: `${targetId}_input` as CustomPortId,
        behavior: 'floating',
        type: 'segment',
        data: null,
    };
}

function routeGroup(name: string, order: number) {
    return {
        group_name: name,
        group_type: 'simple' as const,
        expression: null,
        conditions: [],
        manipulation: null,
        next_node: null,
        valid: true,
        order,
        route_code: name,
        dock_visible: true,
    };
}

// A CDT at y=220 with 3 route rows, so Default's port centre is y=490 and Error's y=550.
const cdt = makeNode('cdt', NodeType.CLASSIFICATION_TABLE, {
    y: 220,
    height: 60 + 60 * 5,
    ports: [port('cdt', 'decision-default'), port('cdt', 'decision-error')],
    data: { table: { condition_groups: ['row1', 'row2', 'row3'].map((name, i) => routeGroup(name, i)) } },
});
const end = makeNode('end', NodeType.END, { height: 60 });

describe('computeRowSnapY', () => {
    const connections = [conn('c1', 'cdt', 'decision-default', 'end'), conn('c2', 'cdt', 'decision-error', 'end')];
    const snap = (proposedY: number) => computeRowSnapY(end, { x: 0, y: proposedY }, [cdt, end], connections);

    it.each([
        [480, 490], // midpoint between Default (top 460) and Error (top 520)
        [500, 490],
        [460, 460], // Default row
        [522, 520], // Error row
    ])('snaps a node fed by two rows: proposed %i -> %i', (proposedY, expectedY) => {
        expect(snap(proposedY)).toBe(expectedY);
    });

    it('does not snap when every candidate is beyond the threshold', () => {
        expect(snap(580)).toBeNull();
    });

    it('still snaps to the single row when only one row feeds the node', () => {
        const single = [conn('c1', 'cdt', 'decision-error', 'end')];
        expect(computeRowSnapY(end, { x: 0, y: 500 }, [cdt, end], single)).toBe(520);
        // No second row, so no midpoint: 480 is 40px from Error's 520 — out of range.
        expect(computeRowSnapY(end, { x: 0, y: 480 }, [cdt, end], single)).toBeNull();
    });
});
