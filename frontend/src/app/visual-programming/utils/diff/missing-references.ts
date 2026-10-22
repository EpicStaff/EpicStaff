import { NodeType } from '@shared/models';

import { NodeModel } from '../../core/models/node.model';
import { FieldName } from './field-display';
import { MissingReference } from './types';

/** The version-side inputs of one version node. */
interface VersionNodeInputs {
    warningReferences: readonly MissingReference[] | undefined;
    keyValueTableName: string | undefined;
}

/**
 * Everything the version node referenced that no longer exists: the warning-based references (deleted
 * secrets included), then the Key-Value table, stored by name, that the preview could not re-bind
 * (the backend re-binds it without a warning).
 */
export function collectMissingReferences(versionNode: NodeModel, inputs: VersionNodeInputs): MissingReference[] {
    return [...(inputs.warningReferences ?? []), ...missingKeyValueTable(versionNode, inputs.keyValueTableName)];
}

function missingKeyValueTable(node: NodeModel, tableName: string | undefined): MissingReference[] {
    if (node.type !== NodeType.KEY_VALUE || !tableName || node.data.key_value_table !== null) return [];
    const path: FieldName = 'key_value_table';
    return [{ path, field: path, missing: tableName, source: 'keyValueTable' }];
}
