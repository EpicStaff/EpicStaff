/** Backend DTO for GraphNote */
export interface GraphNote {
    id: number;
    node_name: string;
    graph: number;
    content: string;
    metadata: Record<string, unknown>;
}
