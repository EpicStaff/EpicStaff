import { NodeType } from '@shared/models';

import { FlowModel } from '../../core/models/flow.model';
import { NodeModel } from '../../core/models/node.model';
import { FieldName } from './field-display';
import { MissingReference, VersionKeyValueTableNames, VersionWarningReferences } from './types';

/**
 * Everything each version node referenced that no longer exists, by version canvas node id (only nodes with
 * at least one): the warning-based references (deleted secrets included), then the ones only the frontend
 * finds (`buildFrontendFoundReferences`). Version side only: the diff engine reads it for its entries, and
 * the plain preview for its markers, without building a diff.
 */
export function buildVersionMissingReferences(
    versionFlow: FlowModel,
    versionWarningReferences: VersionWarningReferences,
    frontendFoundReferences: ReadonlyMap<string, readonly MissingReference[]>
): ReadonlyMap<string, readonly MissingReference[]> {
    const references = new Map<string, readonly MissingReference[]>();
    for (const node of versionFlow.nodes) {
        const found = [
            ...(versionWarningReferences.get(node.id) ?? []),
            ...(frontendFoundReferences.get(node.id) ?? []),
        ];
        if (found.length > 0) references.set(node.id, found);
    }
    return references;
}

/**
 * The missing references of the version that no backend warning covers, by version canvas node id: today
 * only the Key-Value table the preview could not re-bind. Needs the version side only, not the live
 * canvas, so the preview can list them without building the diff. If the backend ever warns about an
 * unbound Key-Value table, remove this source (the warning becomes the only one) instead of deduplicating.
 */
export function buildFrontendFoundReferences(
    versionFlow: FlowModel,
    versionKeyValueTableNames: VersionKeyValueTableNames
): ReadonlyMap<string, readonly MissingReference[]> {
    const references = new Map<string, MissingReference[]>();
    for (const node of versionFlow.nodes) {
        const found = missingKeyValueTable(node, versionKeyValueTableNames.get(node.id));
        if (found.length > 0) references.set(node.id, found);
    }
    return references;
}

function missingKeyValueTable(node: NodeModel, tableName: string | undefined): MissingReference[] {
    if (node.type !== NodeType.KEY_VALUE || !tableName || node.data.key_value_table !== null) return [];
    const path: FieldName = 'key_value_table';
    return [{ path, field: path, missing: tableName, source: 'keyValueTable' }];
}
