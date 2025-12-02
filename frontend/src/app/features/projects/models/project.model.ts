import { Session } from '../../../shared/models/sesson.model';
import { GetCrewTagRequest } from './crew-tag.model';
export enum ProjectProcess {
    SEQUENTIAL = 'sequential',
    HIERARCHICAL = 'hierarchical',
}
export interface GetProjectRequest {
    id: number;
    name: string;
    description: string | null;
    process: ProjectProcess;

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
    similarity_threshold?: string | null;
    search_limit?: number | null;

    planning_llm_config: number | null;
    manager_llm_config: number | null;
    embedding_config: number | null;
    memory_llm_config: number | null;
    metadata?: any | null;

    is_template: boolean;
}

export interface CreateProjectRequest {
    name: string;
    description: string | null;
    process: ProjectProcess;

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
    similarity_threshold?: string | null;
    search_limit?: number | null;
    is_template: boolean;

}

export interface UpdateProjectRequest {
    id: number;
    name: string;
    description: string | null;
    process: ProjectProcess;
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
    is_template?: boolean;

}
