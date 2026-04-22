import { DecisionTableNodeModel, LLMNodeModel, NodeModel, SubGraphNodeModel } from '../models/node.model';
import { NodeType } from './node-type';

/** Strips any auto-generated counter suffix, e.g. "Python-Node (#2)" or "Python-Node #2" → "Python-Node" */
function stripCounter(name: string | null | undefined): string {
    if (!name) return '';
    return name
        .replace(/\s*\(#\d+\)\s*$/, '')
        .replace(/\s*#\d+\s*$/, '')
        .trim();
}

/** Returns "Base Name #N" where N is the nodeNumber, or just "Base Name" if no number. */
function withNumber(baseName: string, node: NodeModel): string {
    if (node.nodeNumber != null) {
        return `${baseName} #${node.nodeNumber}`;
    }
    return baseName;
}

export function getNodeTitle(node: NodeModel): string {
    if (!node) return 'Unknown Node';
    switch (node.type) {
        // Node types where the user edits the name — return node_name as-is.
        // The #N badge is displayed separately above the node.
        case NodeType.PROJECT:
        case NodeType.PYTHON:
        case NodeType.FILE_EXTRACTOR:
        case NodeType.AUDIO_TO_TEXT:
        case NodeType.WEBHOOK_TRIGGER:
        case NodeType.TELEGRAM_TRIGGER:
        case NodeType.CODE_AGENT:
            return node.node_name || '';
        // Entity-name types — display the referenced entity name with the badge number.
        case NodeType.TABLE:
            return withNumber(stripCounter((node as DecisionTableNodeModel).data.name), node);
        case NodeType.LLM:
            return withNumber(stripCounter((node as LLMNodeModel).data.custom_name), node);
        // Fixed-name types
        case NodeType.START:
            return withNumber('Start', node);
        case NodeType.END:
            return withNumber('End', node);
        case NodeType.NOTE:
            return 'Note';
        case NodeType.SUBGRAPH:
            const subgraphNode = node as SubGraphNodeModel;
            if (subgraphNode.isBlocked || !subgraphNode.data?.name) {
                return 'Deleted Flow';
            }
            return subgraphNode.data.name;
        default:
            return '';
    }
}
// export function getNodeTitle(node: NodeModel): string {
//     if (!node) return 'Unknown Node';
//     switch (node.type) {
//         // Node types where the user edits the name — return node_name as-is.
//         // The #N badge is displayed separately above the node.
//         case NodeType.PROJECT:
//         case NodeType.PYTHON:
//             return (node as PythonNodeModel).node_name || '';

//         case NodeType.TABLE:
//             return (node as { data: { name?: string } }).data.name || '';
//         case NodeType.CLASSIFICATION_TABLE:
//             return (node as { data: { name?: string } }).data.name || '';
//         case NodeType.LLM:
//             return (node as { data: { custom_name?: string } }).data.custom_name || '';
//         case NodeType.START:
//             return 'Start';
//         case NodeType.NOTE:
//             return 'Note';
//         case NodeType.FILE_EXTRACTOR:
//         case NodeType.AUDIO_TO_TEXT:
//         case NodeType.WEBHOOK_TRIGGER:
//         case NodeType.TELEGRAM_TRIGGER:
//         case NodeType.CODE_AGENT:
//             return node.node_name || '';
//         // Entity-name types — display the referenced entity name with the badge number.
//         case NodeType.TABLE:
//             return withNumber(stripCounter((node as DecisionTableNodeModel).data.name), node);
//         case NodeType.LLM:
//             return withNumber(stripCounter((node as LLMNodeModel).data.custom_name), node);
//         // Fixed-name types
//         case NodeType.START:
//             return withNumber('Start', node);
//         case NodeType.END:
//             return withNumber('End', node);
//         case NodeType.NOTE:
//             return 'Note';
//         case NodeType.SUBGRAPH:
//             const subgraphNode = node as SubGraphNodeModel;
//             if (subgraphNode.isBlocked || !subgraphNode.data?.name) {
//                 return 'Deleted Flow';
//             }
//             return subgraphNode.data.name;
//         default:
//             return '';
//     }
// }
