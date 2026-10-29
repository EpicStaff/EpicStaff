import { NodeType } from '@shared/models';

import { getDefaultNodeSize, readNoteSize } from '../../core/helpers/node-size.util';
import { NodeDtoMetadata } from '../../core/models/node-metadata.model';

/**
 * Size comes from frontend constants, so stale values stored in the backend
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
        size: nodeType === NodeType.NOTE ? readNoteSize(metadata) : getDefaultNodeSize(nodeType),
    };
}
