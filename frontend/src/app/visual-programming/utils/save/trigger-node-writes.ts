import { isTriggerNodeType } from '../../core/helpers/trigger-node-type.util';
import { NodeModel } from '../../core/models/node.model';
import { NodeDiff, NodeDiffByType } from './types';

/**
 * Whether saving this diff would create or change a trigger node (Webhook, Telegram, Schedule), which the
 * backend refuses without Flows:Use. Deleting one is not a write here: it needs only Flows:Update.
 */
export function hasTriggerNodeWrites(nodeDiff: NodeDiffByType): boolean {
    const typeDiffs: NodeDiff<NodeModel>[] = Object.values(nodeDiff);
    return typeDiffs.some(
        (typeDiff) =>
            typeDiff.toCreate.some((node) => isTriggerNodeType(node.type)) ||
            typeDiff.toUpdate.some(({ current }) => isTriggerNodeType(current.type))
    );
}
