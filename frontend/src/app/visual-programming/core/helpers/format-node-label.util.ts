import { formatNodeLabel } from '@shared/utils';

import { NodeModel } from '../models/node.model';
import { isNumberedNodeType } from './node-number.util';

/** Whether `formatCanvasTitle` appends the node's number to `title`: the node is numbered and the title is a name. */
export function canvasTitleCarriesNumber(title: string, node: Pick<NodeModel, 'type' | 'nodeNumber'>): boolean {
    return !!title && node.nodeNumber != null && isNumberedNodeType(node.type);
}

/** The title a canvas node shows when numbers are shown in titles: "Name #N", or `title` as it is when there is nothing to append to. */
export function formatCanvasTitle(title: string, node: Pick<NodeModel, 'type' | 'nodeNumber'>): string {
    return canvasTitleCarriesNumber(title, node)
        ? formatNodeLabel({ node_name: title, nodeNumber: node.nodeNumber })
        : title;
}
