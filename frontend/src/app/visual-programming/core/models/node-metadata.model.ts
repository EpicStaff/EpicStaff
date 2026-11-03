/**
 * What the load mapper builds from the backend `metadata` JSON field of a node
 * (node-dto-metadata-to-flow-metadata.mapper.ts). `position` is read from the backend. `size`
 * comes from frontend constants, except for a note: a note is user-resizable, so its size is read
 * from the backend too.
 */
export interface NodeDtoMetadata {
    position: { x: number; y: number };
    size: { width: number; height: number };
}
