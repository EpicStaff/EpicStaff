import { NODE_COLORS, NODE_ICONS, NodeType } from '@shared/models';

import { NodeDtoMetadata } from '../../core/models/node-metadata.model';
import { clamp, clampPosition, isFiniteNumber } from './metadata-bounds';

const DEFAULT_SIZE = { width: 330, height: 60 };
const MIN_SIZE = 1;
const MAX_SIZE = 10_000;

function finiteNumberOr(value: unknown, fallback: number): number {
    return isFiniteNumber(value) ? value : fallback;
}

export function mapNodeDtoMetadataToFlowNodeMetadata(
    metadata: Record<string, unknown> | undefined | null,
    nodeType: NodeType
): NodeDtoMetadata {
    const m = metadata ?? {};
    const position = m['position'] as { x?: unknown; y?: unknown } | undefined | null;
    const size = m['size'] as { width?: unknown; height?: unknown } | undefined | null;

    return {
        position: {
            x: clampPosition(finiteNumberOr(position?.x, 0)),
            y: clampPosition(finiteNumberOr(position?.y, 0)),
        },
        color: typeof m['color'] === 'string' ? m['color'] : NODE_COLORS[nodeType],
        icon: typeof m['icon'] === 'string' ? m['icon'] : NODE_ICONS[nodeType],
        size: {
            width: clamp(finiteNumberOr(size?.width, DEFAULT_SIZE.width), MIN_SIZE, MAX_SIZE),
            height: clamp(finiteNumberOr(size?.height, DEFAULT_SIZE.height), MIN_SIZE, MAX_SIZE),
        },
    };
}
