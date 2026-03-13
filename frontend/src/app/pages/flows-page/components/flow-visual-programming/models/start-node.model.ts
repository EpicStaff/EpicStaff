export interface StartNode {
  id: number;
  graph: number;
  node_name: string;
  variables: Record<string, any>; // This indicates variables is a JSON object
  metadata: Record<string, any>;
}

export interface CreateStartNodeRequest {
  graph: number;
  variables: Record<string, any>; // This indicates variables is a JSON object
  metadata?: Record<string, any>;
}
