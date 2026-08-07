export type GraphRagDocumentStatus = 'new' | 'completed' | 'failed';

export interface GraphRagDocumentListResponse {
    graph_rag_id: number;
    total_documents: number;
    documents: GraphRagDocument[];
}

export interface GraphRagDocument {
    graph_rag_document_id: number;
    document_id: number;
    file_name: string;
    file_size: number;
    status: GraphRagDocumentStatus;
    created_at: string;
}
