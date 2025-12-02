import { NodeType } from './node-type';
import {
    NodeModel,
    ProjectNodeModel,
    PythonNodeModel,
    NoteNodeModel,
} from '../models/node.model';

export function getNodeTitle(node: NodeModel): string {
    if (!node) return 'Unknown Node';
    switch (node.type) {
        case NodeType.AGENT:
            return (node as any).data.role || '';
        case NodeType.PROJECT:
            return (node as ProjectNodeModel).data.name || '';

        case NodeType.TASK:
            return (node as any).data.name || '';
        case NodeType.PYTHON:
            return (node as PythonNodeModel).node_name || '';

        case NodeType.TOOL:
            return (node as any).data.name || '';
        case NodeType.TABLE:
            return (node as any).data.name || '';
        case NodeType.LLM:
            return (node as any).data.custom_name || '';
        case NodeType.START:
            return 'Start';
        case NodeType.NOTE:
            return 'Note';
        case NodeType.FILE_EXTRACTOR:
            return 'File Extractor';
        case NodeType.WEBHOOK_TRIGGER:
            return (node as any).node_name || '';
        case NodeType.END:
            return 'End';
        case NodeType.SUBGRAPH:
            return node.data.name 
            ;
        default:
            return '';
    }
}
