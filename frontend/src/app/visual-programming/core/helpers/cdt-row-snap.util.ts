import { IPoint } from '@foblex/2d';

import { NodeType } from '../enums/node-type';
import { ConnectionModel } from '../models/connection.model';
import { ConditionGroup } from '../models/decision-table.model';
import { ClassificationDecisionTableNodeModel, DecisionTableNodeModel, NodeModel } from '../models/node.model';
import { slugifyPortName } from './helpers';
import { CDT_HEADER_HEIGHT, CDT_ROW_HEIGHT, DT_HEADER_HEIGHT, DT_ROW_HEIGHT } from './node-size.util';

/** Vertical distance (px) within which a dropped node's input port magnetically snaps to a
 *  connected Decision Table (plain or Classification) row's output port. */
const ROW_SNAP_THRESHOLD_PX = 30;

/** Either row-based table node type — the plain Decision Table and the Classification
 *  Decision Table share this file's row-geometry formulas (see module comment below). */
export type RowBasedTableNodeModel = DecisionTableNodeModel | ClassificationDecisionTableNodeModel;

/**
 * Shared row-geometry helpers for BOTH decision-table node types (`TABLE`, `CLASSIFICATION_TABLE`),
 * keyed off `tableNode.type`. Exactly ONE definition per formula — see individual functions below.
 */

/**
 * Same row-visibility/order rule as the two node components' `conditionGroups` getters:
 * the CDT additionally requires `dock_visible` and `route_code` (mirroring its template's
 * `@if (group.route_code)` guard); the plain DT has no such guard. Both sort by `order`.
 */
export function getVisibleRouteGroups(tableNode: RowBasedTableNodeModel): ConditionGroup[] {
    const allGroups = (tableNode.data?.table?.condition_groups ?? []) as ConditionGroup[];
    const visible =
        tableNode.type === NodeType.CLASSIFICATION_TABLE
            ? allGroups.filter((group) => group.valid !== false && !!group.dock_visible && !!group.route_code)
            : allGroups.filter((group) => group.valid !== false);
    return visible.sort((a, b) => (a.order ?? Number.MAX_SAFE_INTEGER) - (b.order ?? Number.MAX_SAFE_INTEGER));
}

/**
 * Resolves the 0-based rendered row index for an output port role (route/group rows, then
 * Default, then Error). The CDT matches by `route_code`; the plain DT has none and matches by
 * `group_name` instead — fixing stale rows after a reorder that doesn't change the port count.
 * Accepts either the raw role or its normalized id-suffix form (see slugifyPortName).
 */
export function resolveRowIndex(tableNode: RowBasedTableNodeModel, portRole: string): number | null {
    const routeGroups = getVisibleRouteGroups(tableNode);

    if (portRole === 'decision-default') return routeGroups.length;
    if (portRole === 'decision-error') return routeGroups.length + 1;

    if (tableNode.type === NodeType.CLASSIFICATION_TABLE) {
        const match = /^decision-route-(.+)$/.exec(portRole);
        if (!match) return null;
        const routeKey = slugifyPortName(match[1]);
        const index = routeGroups.findIndex(
            (group) => slugifyPortName(group.route_code || group.group_name) === routeKey
        );
        return index >= 0 ? index : null;
    }

    const match = /^decision-out-(.+)$/.exec(portRole);
    if (!match) return null;
    const groupNameKey = slugifyPortName(match[1]);
    const index = routeGroups.findIndex((group) => slugifyPortName(group.group_name) === groupNameKey);
    return index >= 0 ? index : null;
}

/**
 * The one copy of the row-port-centre formula, taking the table's top y explicitly so callers
 * that only know the node's future centre (e.g. auto-arrange, before positions are assigned)
 * can compute an offset without a real node model — just its type.
 */
export function getRowPortCenterYFromTop(
    topY: number,
    rowIndex: number,
    nodeType: NodeType.TABLE | NodeType.CLASSIFICATION_TABLE
): number {
    const [headerHeight, rowHeight] =
        nodeType === NodeType.TABLE ? [DT_HEADER_HEIGHT, DT_ROW_HEIGHT] : [CDT_HEADER_HEIGHT, CDT_ROW_HEIGHT];
    return topY + headerHeight + rowHeight * rowIndex + rowHeight / 2;
}

/**
 * Exported so `getPortPosition` (segment-avoidance.helper.ts) computes an output port's
 * true y-position with this same formula, rather than duplicating it.
 */
export function getRowPortCenterY(tableNode: RowBasedTableNodeModel, rowIndex: number): number {
    return getRowPortCenterYFromTop(tableNode.position.y, rowIndex, tableNode.type);
}

/**
 * If `draggedNode`'s incoming connection comes from a Decision Table row's output port, and the
 * proposed y places its (centred) input port within `ROW_SNAP_THRESHOLD_PX` of that row's centre,
 * returns the aligned y; otherwise null. Only the y axis is touched — x is the caller's concern.
 */
export function computeRowSnapY(
    draggedNode: NodeModel,
    proposedPosition: IPoint,
    allNodes: NodeModel[],
    connections: ConnectionModel[]
): number | null {
    const incomingTableConnection = connections.find((connection) => {
        if (connection.targetNodeId !== draggedNode.id) return false;
        const sourceNode = allNodes.find((n) => n.id === connection.sourceNodeId);
        return sourceNode?.type === NodeType.CLASSIFICATION_TABLE || sourceNode?.type === NodeType.TABLE;
    });
    if (!incomingTableConnection) return null;

    const tableNode = allNodes.find((n) => n.id === incomingTableConnection.sourceNodeId);
    if (!tableNode || (tableNode.type !== NodeType.CLASSIFICATION_TABLE && tableNode.type !== NodeType.TABLE)) {
        return null;
    }

    const portRole = tableNode.ports?.find((p) => p.id === incomingTableConnection.sourcePortId)?.role;
    if (!portRole) return null;

    const rowIndex = resolveRowIndex(tableNode, portRole);
    if (rowIndex === null) return null;

    const portCenterY = getRowPortCenterY(tableNode, rowIndex);
    const targetY = portCenterY - draggedNode.size.height / 2;

    if (Math.abs(proposedPosition.y - targetY) > ROW_SNAP_THRESHOLD_PX) return null;

    return targetY;
}
