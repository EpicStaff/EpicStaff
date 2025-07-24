import { Session } from '../../../shared/models/sesson.model';
import { GetCrewTagRequest } from './crew-tag.model';

export interface GetProjectRequest {
  id: number;
  name: string;
  description: string | null;
  process: 'sequential' | 'hierarchical';

  tasks: number[];
  agents: number[];
  tags: number[];

  memory: boolean | null;
  config: any | null;
  max_rpm: number | null;
  cache: boolean | null;
  full_output: boolean;
  default_temperature: number | null;
  planning: boolean;

  planning_llm_config: number | null;
  manager_llm_config: number | null;
  embedding_config: number | null;
  memory_llm_config: number | null;
  metadata?: any | null;
}

// Create Project Request

export interface CreateProjectRequest {
  name: string;
  description: string | null;
  process: 'sequential' | 'hierarchical';
  tasks?: number[];
  agents?: number[];
  tags?: number[];
  memory: boolean | null;
  config?: any | null;
  max_rpm?: number | null;
  cache?: boolean | null;
  full_output?: boolean;
  default_temperature?: number | null;
  planning?: boolean;
  planning_llm_config?: number | null;
  manager_llm_config?: number | null;
  embedding_config?: number | null;
  memory_llm_config?: number | null;
  metadata?: any | null;
}

// Create Project Request
export interface UpdateProjectRequest {
  id: number;
  name: string;
  description: string | null;
  process: 'sequential' | 'hierarchical';
  tasks?: number[];
  agents?: number[];
  tags?: number[];
  memory: boolean | null;
  config?: any | null;
  max_rpm?: number | null;
  cache?: boolean | null;
  full_output?: boolean;
  default_temperature?: number | null;
  planning?: boolean;
  planning_llm_config?: number | null;
  manager_llm_config?: number | null;
  embedding_config?: number | null;
  memory_llm_config?: number | null;
}
