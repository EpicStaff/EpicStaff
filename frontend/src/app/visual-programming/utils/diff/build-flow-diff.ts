import { NodeType } from '@shared/models';

import { NodeModel } from '../../core/models/node.model';
import { collectSemanticEdges, diffEdges } from './diff-edges';
import { diffProjections } from './diff-fields';
import { matchNodes } from './match-nodes';
import { collectMissingReferences } from './missing-references';
import { ProjectionContext, projectNode } from './semantic-projections';
import { FlowDiff, FlowDiffInput, FlowDiffSummary, MissingReference, NodeDiffEntry } from './types';

/**
 * Shows what a restore of the version (`versionFlow`) would do to the current canvas (`liveFlow`).
 * Pure and deterministic: the same input gives the same result, and nothing is read from services
 * or the DOM.
 *
 * - A node in the version only is `added` (a restore adds it); a node on the canvas only is `deleted`.
 * - A matched node is `changed` when a restore adds, deletes or changes at least one field; each
 *   field change reads current → version.
 * - Missing references (what the version had that no longer exists) are listed per node with a
 *   version side. They never change the status: a node whose only finding is a missing reference
 *   stays `unchanged`.
 */
export function buildFlowDiff(input: FlowDiffInput): FlowDiff {
    const { versionFlow, liveFlow } = input;
    const matching = matchNodes(versionFlow.nodes, liveFlow.nodes);
    const missingReferencesOf = (versionNode: NodeModel): MissingReference[] =>
        collectMissingReferences(versionNode, {
            warningReferences: input.versionWarningReferences.get(versionNode.id),
            keyValueTableName: input.versionKeyValueTableNames.get(versionNode.id),
        });

    const nodes: NodeDiffEntry[] = matching.matches.map((match) => {
        const { key, matchedBy, versionNode, currentNode } = match;
        if (versionNode && currentNode) {
            const fields = diffProjections(
                projectNode(currentNode, projectionContext(matching.currentKeyById)),
                projectNode(versionNode, projectionContext(matching.versionKeyById))
            );
            return {
                key,
                matchedBy,
                status: fields.length > 0 ? 'changed' : 'unchanged',
                type: currentNode.type,
                versionNode,
                currentNode,
                fields,
                missingReferences: missingReferencesOf(versionNode),
            };
        }
        if (versionNode) {
            return {
                key,
                matchedBy,
                status: 'added',
                type: versionNode.type,
                versionNode,
                fields: [],
                missingReferences: missingReferencesOf(versionNode),
            };
        }
        return {
            key,
            matchedBy,
            status: 'deleted',
            type: currentNode!.type,
            currentNode,
            fields: [],
            missingReferences: [],
        };
    });

    const edges = diffEdges(
        collectSemanticEdges(liveFlow, matching.currentKeyById),
        collectSemanticEdges(versionFlow, matching.versionKeyById)
    );

    const summary: FlowDiffSummary = {
        added: nodes.filter((node) => node.status === 'added').length,
        deleted: nodes.filter((node) => node.status === 'deleted').length,
        changed: nodes.filter((node) => node.status === 'changed').length,
        unchanged: nodes.filter((node) => node.status === 'unchanged').length,
        edgesAdded: edges.filter((edge) => edge.status === 'added').length,
        edgesDeleted: edges.filter((edge) => edge.status === 'deleted').length,
    };

    const versionNodesWithoutStart = nodes.filter((node) => node.versionNode && node.type !== NodeType.START);
    const matchedByUuid = versionNodesWithoutStart.filter((node) => node.matchedBy === 'uuid').length;
    const matchRate = versionNodesWithoutStart.length === 0 ? 1 : matchedByUuid / versionNodesWithoutStart.length;

    return { nodes, edges, summary, matchRate };
}

function projectionContext(keyById: ReadonlyMap<string, string>): ProjectionContext {
    return { nodeKey: (canvasId) => (canvasId ? (keyById.get(canvasId) ?? null) : null) };
}
