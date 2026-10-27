import { formatNodeLabel } from '@shared/utils';

import { NodeModel } from '../../../../core/models/node.model';

/** Words of the missing-reference notes ("routes to a node that no longer exists"). */
const UNKNOWN_NODE = 'a node that no longer exists';

/**
 * How the field mark of a decision table route names the node it leads to: as the route select lists it, by the label
 * of that node on the canvas. A route value in the diff is the node's match key, which `nodeIdOfKey` turns into the
 * canvas id; a key no canvas node has reads like the missing-reference notes.
 */
export function routeTargetFormat(
    nodeIdOfKey: (key: string) => string | null,
    nodes: () => readonly NodeModel[]
): (value: unknown) => string {
    return (value) => {
        const nodeId = typeof value === 'string' ? nodeIdOfKey(value) : null;
        const node = nodeId === null ? undefined : nodes().find((candidate) => candidate.id === nodeId);
        return node ? formatNodeLabel(node) : UNKNOWN_NODE;
    };
}
