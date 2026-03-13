export interface Edge {
  id: number;
  start_key: string;
  end_key: string;
  graph: number;
  metadata: Record<string, any>;
}
export interface CreateEdgeRequest {
  start_key: string;
  end_key: string;
  graph: number;
  metadata?: Record<string, any>;
}
