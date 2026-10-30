import { GraphNoteModel, NodeModel } from '../../core/models/node.model';

/** Colour, icon and size come from frontend constants, so only the position is persisted. */
export function toNodeMetadata(node: NodeModel): { position: { x: number; y: number } } {
    return { position: node.position };
}

/** A note is user-resizable and user-coloured, so unlike other nodes it persists both. */
export function toNoteMetadata(node: GraphNoteModel): {
    position: { x: number; y: number };
    size: { width: number; height: number };
    backgroundColor: string | null;
} {
    return {
        ...toNodeMetadata(node),
        size: node.size,
        backgroundColor: node.data.backgroundColor ?? null,
    };
}
