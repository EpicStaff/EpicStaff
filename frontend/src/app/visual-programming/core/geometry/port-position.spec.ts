import { NodeType } from '@shared/models';

import { CDT_INPUT_PORT_CENTER_Y_OFFSET, DT_INPUT_PORT_CENTER_Y_OFFSET } from '../helpers/node-size.util';
import { NodeModel } from '../models/node.model';
import { CustomPortId, ViewPort } from '../models/port.model';
import { getPortPosition, portOffsetFromTop } from './port-position';

function port(nodeId: string, role: string, position: ViewPort['position']): ViewPort {
    return {
        id: `${nodeId}_${role}` as CustomPortId,
        port_type: position === 'left' ? 'input' : 'output',
        role,
        multiple: true,
        label: role,
        allowedConnections: [],
        position,
    };
}

function node(id: string, type: NodeType, height: number, ports: ViewPort[], data: unknown = null): NodeModel {
    return {
        id,
        type,
        position: { x: 400, y: 1000 },
        size: { width: 330, height },
        ports,
        data,
    } as unknown as NodeModel;
}

function tableNode(id: string, type: NodeType.TABLE | NodeType.CLASSIFICATION_TABLE, rowNames: string[]): NodeModel {
    const rolePrefix = type === NodeType.TABLE ? 'decision-out-' : 'decision-route-';
    const ports = [port(id, 'table-in', 'left'), ...rowNames.map((name) => port(id, rolePrefix + name, 'right'))];
    const conditionGroups = rowNames.map((name, order) => ({
        group_name: name,
        route_code: name,
        dock_visible: true,
        valid: true,
        order,
    }));
    return node(id, type, 60 + 60 * (rowNames.length + 2), ports, {
        name: id,
        table: { condition_groups: conditionGroups },
    });
}

function portByRole(target: NodeModel, role: string): ViewPort {
    return target.ports!.find((candidate) => candidate.role === role)!;
}

describe('portOffsetFromTop', () => {
    it('puts a 330x60 python node’s input and output ports at its vertical centre', () => {
        const python = node('py', NodeType.PYTHON, 60, [
            port('py', 'python-in', 'left'),
            port('py', 'python-out', 'right'),
        ]);

        expect(portOffsetFromTop(python, portByRole(python, 'python-out'))).toBe(30);
        expect(portOffsetFromTop(python, portByRole(python, 'python-in'))).toBe(30);
    });

    it('resolves CDT route rows by route_code and the input port by its wrapper offset', () => {
        const cdt = tableNode('cdt', NodeType.CLASSIFICATION_TABLE, ['alpha', 'beta', 'gamma']);

        expect(portOffsetFromTop(cdt, portByRole(cdt, 'decision-route-alpha'))).toBe(90);
        expect(portOffsetFromTop(cdt, portByRole(cdt, 'decision-route-gamma'))).toBe(210);
        expect(portOffsetFromTop(cdt, portByRole(cdt, 'table-in'))).toBe(CDT_INPUT_PORT_CENTER_Y_OFFSET);
    });

    it('resolves DT rows by group_name', () => {
        const dt = tableNode('dt', NodeType.TABLE, ['first', 'second']);

        expect(portOffsetFromTop(dt, portByRole(dt, 'decision-out-first'))).toBe(90);
        expect(portOffsetFromTop(dt, portByRole(dt, 'decision-out-second'))).toBe(150);
        expect(portOffsetFromTop(dt, portByRole(dt, 'table-in'))).toBe(DT_INPUT_PORT_CENTER_Y_OFFSET);
    });

    it('falls back to the left input port when the port is undefined', () => {
        const python = node('py', NodeType.PYTHON, 60, []);

        expect(getPortPosition(python, undefined)).toEqual({ x: 395, y: 1030 });
        expect(portOffsetFromTop(python, undefined)).toBe(30);
    });
});

describe('getPortPosition — f-flow anchor offset', () => {
    it('offsets a table row output port +7 (port-circle radius) past the node edge', () => {
        const defaultRow = port('cdt8', 'decision-default', 'right');
        const cdt8: NodeModel = {
            ...tableNode('cdt8', NodeType.CLASSIFICATION_TABLE, ['a', 'b', 'c', 'd', 'e', 'f', 'g']),
            position: { x: 2180, y: 490 },
            size: { width: 330, height: 540 },
            ports: [defaultRow],
        };

        expect(getPortPosition(cdt8, defaultRow)).toEqual({ x: 2517, y: 1000 });
    });

    it('offsets a default-node left input port -5 (radius 7 minus the 2px wrapper inset)', () => {
        const input = port('end', 'in', 'left');
        const end: NodeModel = { ...node('end', NodeType.AGENT, 60, [input]), position: { x: 3560, y: 596 } };

        expect(getPortPosition(end, input)).toEqual({ x: 3555, y: 626 });
    });
});

describe('getPortPosition — plain Decision Table row geometry', () => {
    it('resolves a DT output port by group_name after a reorder, not by its stored ports-array position', () => {
        // Ports were generated when 'alpha' was order 0 and 'beta' was order 1 — that array
        // order never changes on a pure reorder (normalize-flow-ports only regenerates on a
        // port-count change). The groups have since been reordered: beta is now order 0.
        const alphaPort = port('dt', 'decision-out-alpha', 'right');
        const betaPort = port('dt', 'decision-out-beta', 'right');
        const dt: NodeModel = {
            ...tableNode('dt', NodeType.TABLE, ['beta', 'alpha']),
            position: { x: 0, y: 0 },
            ports: [port('dt', 'table-in', 'left'), alphaPort, betaPort],
        };

        expect(getPortPosition(dt, alphaPort).y).toBe(60 + 60 * 1 + 30);
        expect(getPortPosition(dt, betaPort).y).toBe(60 + 60 * 0 + 30);
    });

    it('places the DT input port at y + 30 (the .input-port-wrapper centre), not the body middle', () => {
        const dt: NodeModel = { ...tableNode('dt', NodeType.TABLE, []), position: { x: 100, y: 200 } };

        // x: 93 is f-flow's port-element anchor (7px left of the node edge for a table input port) — not a bug.
        expect(getPortPosition(dt, portByRole(dt, 'table-in'))).toEqual({ x: 93, y: 230 });
    });
});
