import { RestoreWarning } from '../../features/flows/models/graph.model';
import { SnapshotNode } from '../../features/flows/models/graph-version-preview.model';
import { MissingReference } from '../utils/diff';

/**
 * Warnings-dialog entries for the missing references no backend warning covers, in snapshot node order.
 * They are worded like the backend warnings and anchored the same way (the snapshot `node_id`), so the
 * dialog shows "In node X, …" and opens the node through whichever canvas is bound.
 * `referencesByCanvasId` is `buildFrontendFoundReferences` of the version, keyed by version canvas node id.
 */
export function buildFrontendFoundWarnings(
    snapshotNodes: readonly SnapshotNode[],
    referencesByCanvasId: ReadonlyMap<string, readonly MissingReference[]>,
    snapshotIdToCanvasId: ReadonlyMap<number, string>
): RestoreWarning[] {
    return snapshotNodes.flatMap((node) => {
        const canvasId = snapshotIdToCanvasId.get(node.id);
        const references = canvasId === undefined ? [] : (referencesByCanvasId.get(canvasId) ?? []);
        return references.flatMap((reference) => warningOf(node, reference) ?? []);
    });
}

function warningOf(node: SnapshotNode, reference: MissingReference): RestoreWarning | null {
    switch (reference.source) {
        case 'keyValueTable':
            return {
                type: 'key_value_table_unbound',
                // Named like the backend names a node in its warnings.
                node_name: node.node_name || node.node_type,
                node_type: node.node_type,
                node_id: node.id,
                field: reference.field,
                missing_name: String(reference.missing),
                reason: `Key-Value table "${reference.missing}" no longer exists or cannot be used, so the node has no table.`,
            };
        case 'warning':
            // Never reached: `buildFrontendFoundReferences` returns no warning-based references. Kept so a new
            // source fails the exhaustive switch here instead of being dropped silently.
            return null;
    }
}
