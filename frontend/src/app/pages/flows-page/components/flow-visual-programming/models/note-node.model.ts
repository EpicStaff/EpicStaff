/** Backend DTO for NoteNode */
export interface NoteNode {
    id: number;
    node_name: string;
    graph: number;
    content: string;
    metadata: Record<string, any>;
}

/** Request body for creating / updating a NoteNode */
export interface CreateNoteNodeRequest {
    node_name: string;
    graph: number;
    content: string;
    metadata?: Record<string, any>;
}

