export interface Edge {
  id: number;
  start_node_id: number;
  end_node_id: number;
  graph: number;
  metadata: Record<string, any>;
}
export interface CreateEdgeRequest {
  start_node_id: number;
  end_node_id: number;
  graph: number;
  metadata?: Record<string, any>;
}
