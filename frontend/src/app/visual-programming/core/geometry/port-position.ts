import { IPoint } from '@foblex/2d';
import { NodeType } from '@shared/models';

import { getRowPortCenterY, resolveRowIndex } from '../helpers/cdt-row-snap.util';
import { CDT_INPUT_PORT_CENTER_Y_OFFSET, DT_INPUT_PORT_CENTER_Y_OFFSET } from '../helpers/node-size.util';
import { NodeModel } from '../models/node.model';
import { ViewPort } from '../models/port.model';

const PORT_ELEMENT_RADIUS = 7;
const DEFAULT_NODE_PORT_INSET = 2;
const DEFAULT_NODE_PORT_OFFSET = PORT_ELEMENT_RADIUS - DEFAULT_NODE_PORT_INSET;

/** Where a port's anchor is drawn on the canvas — the single source of port geometry for layout and routing. */
export function getPortPosition(node: NodeModel, port: ViewPort | undefined): IPoint {
    const { x, y } = node.position;
    const { width, height } = node.size;

    let result: IPoint;

    if ((node.type === NodeType.TABLE || node.type === NodeType.CLASSIFICATION_TABLE) && port) {
        // Both table types' input port renders near the top (`.input-port-wrapper`), not at the
        // header's centre. Output-port rows resolve via `resolveRowIndex`/`getRowPortCenterY`
        // (cdt-row-snap.util.ts) — the single shared source of truth for "which row is this".
        if (port.role === 'table-in') {
            const inputOffset =
                node.type === NodeType.TABLE ? DT_INPUT_PORT_CENTER_Y_OFFSET : CDT_INPUT_PORT_CENTER_Y_OFFSET;
            result = { x: x - PORT_ELEMENT_RADIUS, y: y + inputOffset };
        } else {
            const rowIndex = resolveRowIndex(node, port.role);
            const rowX = x + width + PORT_ELEMENT_RADIUS;
            result =
                rowIndex !== null ? { x: rowX, y: getRowPortCenterY(node, rowIndex) } : { x: rowX, y: y + height / 2 };
        }
    } else {
        switch (port?.position) {
            case 'right':
                result = { x: x + width + DEFAULT_NODE_PORT_OFFSET, y: y + height / 2 };
                break;
            case 'top':
                result = { x: x + width / 2, y };
                break;
            case 'bottom':
                result = { x: x + width / 2, y: y + height };
                break;
            default:
                result = { x: x - DEFAULT_NODE_PORT_OFFSET, y: y + height / 2 };
                break;
        }
    }

    return result;
}

/** A port's y offset from its node's top edge, independent of where the node currently sits. */
export function portOffsetFromTop(node: NodeModel, port: ViewPort | undefined): number {
    return getPortPosition({ ...node, position: { x: 0, y: 0 } }, port).y;
}
