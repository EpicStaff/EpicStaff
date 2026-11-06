import { NodeType } from '@shared/models';

import { NodeModel } from '../models/node.model';

/** The ids of the secrets the node's Python code reads (both blocks of a classification table); empty for other nodes. */
export function codeSecretIds(node: NodeModel): number[] {
    switch (node.type) {
        case NodeType.PYTHON:
            return node.data.secret_ids ?? [];
        case NodeType.WEBHOOK_TRIGGER:
            return node.data.python_code.secret_ids ?? [];
        case NodeType.CLASSIFICATION_TABLE:
            return [
                ...(node.data.table.pre_computation?.secret_ids ?? []),
                ...(node.data.table.post_computation?.secret_ids ?? []),
            ];
        default:
            return [];
    }
}
