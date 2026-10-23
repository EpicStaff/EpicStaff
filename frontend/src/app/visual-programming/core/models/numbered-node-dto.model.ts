/**
 * A node the backend numbers within its graph (every type except Start, End and Note). The number is
 * issued by the graph's counter, read-only for the client, and null only on rows the backend has not
 * numbered.
 */
export interface NumberedNodeDto {
    node_number: number | null;
}
