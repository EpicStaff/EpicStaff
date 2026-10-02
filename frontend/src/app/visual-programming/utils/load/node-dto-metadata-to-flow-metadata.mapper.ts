import { NODE_COLORS, NODE_ICONS, NodeType } from '@shared/models';

import { NodeDtoMetadata } from '../../core/models/node-metadata.model';

const DEFAULT_SIZE = { width: 330, height: 60 };

export function mapNodeDtoMetadataToFlowNodeMetadata(
    metadata: Record<string, unknown> | undefined | null,
    nodeType: NodeType
): NodeDtoMetadata {
    const m = metadata ?? {};
    const position = m['position'] as { x?: number; y?: number } | undefined;
    const size = m['size'] as { width?: number; height?: number } | undefined;

    return {
        position: {
            x: position?.x ?? 0,
            y: position?.y ?? 0,
        },
        color: typeof m['color'] === 'string' ? m['color'] : NODE_COLORS[nodeType],
        icon: typeof m['icon'] === 'string' ? m['icon'] : NODE_ICONS[nodeType],
        size: {
            width: size?.width ?? DEFAULT_SIZE.width,
            height: size?.height ?? DEFAULT_SIZE.height,
        },
        nodeNumber: typeof m['nodeNumber'] === 'number' ? m['nodeNumber'] : undefined,
    };
}
