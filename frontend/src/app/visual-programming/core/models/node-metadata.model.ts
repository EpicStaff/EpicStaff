/**
 * The shape of the `metadata` JSON field stored on every backend node.
 * Used in both directions:
 *   - BE → FE: read by node-dto-metadata-to-flow-metadata.mapper.ts at load time
 *   - FE → BE: written by flow-node-metadata.mapper.ts at save time
 */
export interface NodeDtoMetadata extends Record<string, unknown> {
    position: { x: number; y: number };
    color: string;
    icon: string;
    size: { width: number; height: number };
}
