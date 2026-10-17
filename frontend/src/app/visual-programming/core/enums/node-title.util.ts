import { NodeType } from '@shared/models';

import { DecisionTableNodeModel, NodeModel, SubGraphNodeModel } from '../models/node.model';

export function getNodeTitle(node: NodeModel): string {
    if (!node) return 'Unknown Node';

    switch (node.type) {
        // Node types where the user edits the name — return node_name as-is.
        // The #N badge is displayed separately above the node.
        case NodeType.PYTHON:
        case NodeType.FILE_EXTRACTOR:
        case NodeType.AUDIO_TO_TEXT:
        case NodeType.WEBHOOK_TRIGGER:
        case NodeType.TELEGRAM_TRIGGER:
        case NodeType.KNOWLEDGE_RETRIEVER:
        case NodeType.KEY_VALUE:
        case NodeType.SCHEDULE_TRIGGER:
        case NodeType.TASK:
        case NodeType.AGENT:
            return node.node_name || '';

        // Entity-name types — display the referenced entity name.
        case NodeType.TABLE:
            return (node as DecisionTableNodeModel).data.name ?? '';

        // Fixed-name types
        case NodeType.START:
            return 'Start';
        case NodeType.END:
            return 'End';
        case NodeType.NOTE:
            return 'Note';
        case NodeType.SUBGRAPH: {
            const subgraphNode = node as SubGraphNodeModel;
            if (subgraphNode.isBlocked || !subgraphNode.data?.name) {
                return 'Deleted Flow';
            }
            return subgraphNode.data.name;
        }
        default:
            return '';
    }
}
