import { NODE_COLORS, NODE_ICONS, NodeType } from '@shared/models';

import { getDefaultNodeSize, readNoteSize } from '../../core/helpers/node-size.util';
import { NodeDtoMetadata } from '../../core/models/node-metadata.model';

/**
 * Colour, icon and size come from frontend constants, so stale values stored in the backend
 * metadata are ignored. Only the position is read, plus a note's own size.
 */
export function mapNodeDtoMetadataToFlowNodeMetadata(
    metadata: Record<string, unknown> | undefined | null,
    nodeType: NodeType
): NodeDtoMetadata {
    const position = metadata?.['position'] as { x?: number; y?: number } | undefined;

    return {
        position: {
            x: position?.x ?? 0,
            y: position?.y ?? 0,
        },
        color: NODE_COLORS[nodeType],
        icon: NODE_ICONS[nodeType],
        size: nodeType === NodeType.NOTE ? readNoteSize(metadata) : getDefaultNodeSize(nodeType),
    };
}
