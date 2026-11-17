import { NodeType } from '@shared/models';

import { NodeModel } from '../../core/models/node.model';
import { NodeMatchKind } from './types';

export interface NodeMatch {
    key: string;
    matchedBy: NodeMatchKind | null;
    versionNode?: NodeModel;
    currentNode?: NodeModel;
}

export interface NodeMatching {
    /** Version nodes in version order (matched or not), then the current nodes left unmatched. */
    matches: NodeMatch[];
    /** Match key by version canvas node id. */
    versionKeyById: ReadonlyMap<string, string>;
    /** Match key by current canvas node id. */
    currentKeyById: ReadonlyMap<string, string>;
}

const START_KEY = 'start';

/**
 * Pairs version nodes with current nodes: first by node uuid (same type only), then the remaining
 * Start nodes by type, because the editor adds a Start with a new uuid when a flow has none.
 * A node without a uuid never matches by uuid. When one side repeats a uuid, only its first node
 * takes part; the others stay unmatched. Canvas ids and backend ids are never used to match: they
 * change on every load, restore and import. Keys are unique because canvas ids are generated uuids.
 */
export function matchNodes(versionNodes: readonly NodeModel[], currentNodes: readonly NodeModel[]): NodeMatching {
    const currentByUuid = firstNodeByUuid(currentNodes);
    const matchedCurrent = new Set<NodeModel>();
    const pairs = new Map<NodeModel, { currentNode: NodeModel; matchedBy: NodeMatchKind }>();

    for (const [uuid, versionNode] of firstNodeByUuid(versionNodes)) {
        const currentNode = currentByUuid.get(uuid);
        if (!currentNode || currentNode.type !== versionNode.type) continue;
        pairs.set(versionNode, { currentNode, matchedBy: 'uuid' });
        matchedCurrent.add(currentNode);
    }

    const versionStart = versionNodes.find((node) => node.type === NodeType.START && !pairs.has(node));
    const currentStart = currentNodes.find((node) => node.type === NodeType.START && !matchedCurrent.has(node));
    if (versionStart && currentStart) {
        pairs.set(versionStart, { currentNode: currentStart, matchedBy: 'start' });
        matchedCurrent.add(currentStart);
    }

    const matches: NodeMatch[] = [];
    const versionKeyById = new Map<string, string>();
    const currentKeyById = new Map<string, string>();

    for (const versionNode of versionNodes) {
        const pair = pairs.get(versionNode);
        if (pair) {
            const key = pair.matchedBy === 'uuid' ? `uuid:${versionNode.nodeUuid}` : START_KEY;
            matches.push({ key, matchedBy: pair.matchedBy, versionNode, currentNode: pair.currentNode });
            versionKeyById.set(versionNode.id, key);
            currentKeyById.set(pair.currentNode.id, key);
        } else {
            const key = `version:${versionNode.id}`;
            matches.push({ key, matchedBy: null, versionNode });
            versionKeyById.set(versionNode.id, key);
        }
    }

    for (const currentNode of currentNodes) {
        if (matchedCurrent.has(currentNode)) continue;
        const key = `current:${currentNode.id}`;
        matches.push({ key, matchedBy: null, currentNode });
        currentKeyById.set(currentNode.id, key);
    }

    return { matches, versionKeyById, currentKeyById };
}

function firstNodeByUuid(nodes: readonly NodeModel[]): Map<string, NodeModel> {
    const byUuid = new Map<string, NodeModel>();
    for (const node of nodes) {
        if (node.nodeUuid && !byUuid.has(node.nodeUuid)) byUuid.set(node.nodeUuid, node);
    }
    return byUuid;
}
