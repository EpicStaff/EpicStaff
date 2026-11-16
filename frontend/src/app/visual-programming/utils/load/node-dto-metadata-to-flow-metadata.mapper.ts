import { NodeType } from '@shared/models';

import { getDefaultNodeSize, readNoteSize } from '../../core/helpers/node-size.util';
import { NodeDtoMetadata } from '../../core/models/node-metadata.model';
import { clamp, clampPosition, isFiniteNumber } from './metadata-bounds';

const MIN_SIZE = 1;
const MAX_SIZE = 10_000;

function finiteNumberOr(value: unknown, fallback: number): number {
    return isFiniteNumber(value) ? value : fallback;
}

/** A note's own stored size, kept within bounds so a huge stored value cannot break the canvas. */
function readBoundedNoteSize(metadata: Record<string, unknown> | undefined | null): {
    width: number;
    height: number;
} {
    const size = readNoteSize(metadata);
    return {
        width: clamp(size.width, MIN_SIZE, MAX_SIZE),
        height: clamp(size.height, MIN_SIZE, MAX_SIZE),
    };
}

/**
 * Size comes from frontend constants, so stale values stored in the backend
 * metadata are ignored. Only the position is read, plus a note's own size.
 */
export function mapNodeDtoMetadataToFlowNodeMetadata(
    metadata: Record<string, unknown> | undefined | null,
    nodeType: NodeType
): NodeDtoMetadata {
    const position = metadata?.['position'] as { x?: unknown; y?: unknown } | undefined | null;

    return {
        position: {
            x: clampPosition(finiteNumberOr(position?.x, 0)),
            y: clampPosition(finiteNumberOr(position?.y, 0)),
        },
        size: nodeType === NodeType.NOTE ? readBoundedNoteSize(metadata) : getDefaultNodeSize(nodeType),
    };
}

/**
 * Whether a node row still carries a size from before node sizes came from frontend constants, and
 * that size is not the one the node is drawn at now. Such a row was saved at a different size, so
 * the node's ports have moved since and the bends a user placed on its wires no longer meet them.
 * A note is drawn at its stored size, so a note's size is never outdated. A row without a stored
 * size has nothing to compare, so it is not outdated either.
 */
export function hasOutdatedStoredSize(
    metadata: unknown,
    nodeType: NodeType,
    drawnSize: { width: number; height: number }
): boolean {
    if (nodeType === NodeType.NOTE) return false;
    const storedSize = (metadata as { size?: unknown } | null | undefined)?.size;
    if (typeof storedSize !== 'object' || storedSize === null) return false;
    const { width, height } = storedSize as { width?: unknown; height?: unknown };
    return width !== drawnSize.width || height !== drawnSize.height;
}
