/**
 * What the load mapper builds from the backend `metadata` JSON field of a node
 * (node-dto-metadata-to-flow-metadata.mapper.ts). Only `position` is read from the backend;
 * `color`, `icon` and `size` come from frontend constants.
 */
export interface NodeDtoMetadata extends Record<string, unknown> {
    position: { x: number; y: number };
    color: string;
    icon: string;
    size: { width: number; height: number };
}
