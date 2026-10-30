/**
 * What the load mapper builds from the backend `metadata` JSON field of a node
 * (node-dto-metadata-to-flow-metadata.mapper.ts). Only `position` is read from the backend;
 * `size` comes from frontend constants.
 */
export interface NodeDtoMetadata extends Record<string, unknown> {
    position: { x: number; y: number };
    size: { width: number; height: number };
}
