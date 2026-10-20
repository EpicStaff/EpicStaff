import { IPoint } from '@foblex/2d';
import { NodeType } from '@shared/models';

import { getClassificationTableVisualHeight, getDecisionTableVisualHeight } from '../../helpers/node-size.util';
import { ConnectionModel } from '../../models/connection.model';
import { NodeModel } from '../../models/node.model';
import { CustomPortId, ViewPort } from '../../models/port.model';

/** Test-only builders for the layout and router specs. Nothing here is imported by app code. */

/** A flow fixture: a set of nodes and their connections ready for layout or routing tests. */
export interface FlowFixture {
    nodes: NodeModel[];
    connections: ConnectionModel[];
}

type RowBasedTableType = NodeType.TABLE | NodeType.CLASSIFICATION_TABLE;

/** Creates a single port on `nodeId` with the given `role` and `position`. */
export function port(nodeId: string, role: string, position: ViewPort['position']): ViewPort {
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

/**
 * Creates a minimal node for layout tests.
 * Defaults: 330x100, position (0,0), no ports, null data.
 */
export function makeNode(
    id: string,
    type: NodeType,
    options: { width?: number; height?: number; position?: IPoint; ports?: ViewPort[]; data?: unknown } = {}
): NodeModel {
    return {
        id,
        type,
        node_name: id,
        position: options.position ?? { x: 0, y: 0 },
        size: { width: options.width ?? 330, height: options.height ?? 100 },
        ports: options.ports ?? [],
        data: options.data ?? null,
    } as unknown as NodeModel;
}

/** Creates a connection between two ports, identified by node id + role. */
export function connect(
    id: string,
    sourceId: string,
    sourceRole: string,
    targetId: string,
    targetRole = 'input'
): ConnectionModel {
    return {
        id,
        category: 'default',
        sourceNodeId: sourceId,
        targetNodeId: targetId,
        sourcePortId: `${sourceId}_${sourceRole}` as CustomPortId,
        targetPortId: `${targetId}_${targetRole}` as CustomPortId,
        behavior: 'floating',
        type: 'segment',
        data: null,
    };
}

/** Returns the output-port role for a table row at `rowIndex`. */
export function tableRowRole(type: RowBasedTableType, rowIndex: number): string {
    return (type === NodeType.TABLE ? 'decision-out-' : 'decision-route-') + `row-${rowIndex}`;
}

/**
 * A row-based table with rows `row-0..row-N-1`, its `table-in` port and one output port per row.
 * The height is the rendered (visual) height, as `normalizeTableNodeSize` sets it in the app.
 */
export function tableNode(id: string, type: RowBasedTableType, rowCount: number, position?: IPoint): NodeModel {
    const rowNames = Array.from({ length: rowCount }, (_, rowIndex) => `row-${rowIndex}`);
    const conditionGroups = rowNames.map((name, order) => ({
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
    }));
    const height =
        type === NodeType.TABLE
            ? getDecisionTableVisualHeight(conditionGroups)
            : getClassificationTableVisualHeight(conditionGroups);
    return makeNode(id, type, {
        height,
        position,
        ports: [
            port(id, 'table-in', 'left'),
            ...rowNames.map((_, rowIndex) => port(id, tableRowRole(type, rowIndex), 'right')),
        ],
        data: { name: id, table: { condition_groups: conditionGroups } },
    });
}

/** Registers every port a connection references and the node lacks: sources on the right, targets on the left. */
export function withPorts(nodes: NodeModel[], connections: ConnectionModel[]): NodeModel[] {
    return nodes.map((node) => {
        const ports = [...(node.ports ?? [])];
        const addPort = (portId: string, position: ViewPort['position']): void => {
            if (ports.some((existing) => existing.id === portId)) return;
            ports.push(port(node.id, portId.slice(node.id.length + 1), position));
        };
        for (const connection of connections) {
            if (connection.sourceNodeId === node.id) addPort(connection.sourcePortId, 'right');
            if (connection.targetNodeId === node.id) addPort(connection.targetPortId, 'left');
        }
        return { ...node, ports };
    });
}

/** Moves every node that has an entry in `positions`; the rest keep theirs. */
export function withPositions(nodes: NodeModel[], positions: Map<string, IPoint>): NodeModel[] {
    return nodes.map((node) => {
        const position = positions.get(node.id);
        return position ? { ...node, position: { x: position.x, y: position.y } } : node;
    });
}

/** Wraps nodes and connections into a `FlowFixture`, auto-registering missing ports via `withPorts`. */
export function fixture(nodes: NodeModel[], connections: ConnectionModel[]): FlowFixture {
    return { nodes: withPorts(nodes, connections), connections };
}
