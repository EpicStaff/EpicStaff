import {
  GetPythonCodeRequest,
  CreatePythonCodeRequest,
  CustomPythonCode,
} from '../../../../../features/tools/models/python-code.model';

export interface ConditionalEdge {
  id: number;
  graph: number;
  source_node_id: number;
  python_code: GetPythonCodeRequest;
  input_map: Record<string, any>;
  metadata: Record<string, any>;
}
export interface GetConditionalEdgeRequest {
  id: number;
  graph: number;
  source_node_id: number;
  python_code: GetPythonCodeRequest;
  input_map: Record<string, any>;
  metadata: Record<string, any>;
}
export interface CreateConditionalEdgeRequest {
  graph: number;
  source_node_id: number | null;
  python_code: CreatePythonCodeRequest;
  input_map: Record<string, any>;
  metadata?: Record<string, any>;
}

export interface CustomConditionalEdgeModelForNode {
  id?: number;
  source: string | null;
  then: string | null;
  python_code: CustomPythonCode;
  input_map: Record<string, any>;
}
