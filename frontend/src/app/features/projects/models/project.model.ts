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
    config: Record<string, unknown> | null;
    max_rpm: number | null;
    cache: boolean | null;
    full_output: boolean;
    default_temperature: number | null;
    planning: boolean;
    similarity_threshold?: number | null;
    search_limit?: number | null;

    planning_llm_config: number | null;
    manager_llm_config: number | null;
    embedding_config: number | null;
    memory_llm_config: number | null;
    metadata?: Record<string, unknown> | null;
}

export interface CreateProjectRequest {
    name: string;
    description: string | null;
    process: ProjectProcess;

    tasks?: number[];
    agents?: number[];
    tags?: number[];
    memory: boolean | null;
    config?: Record<string, unknown> | null;
    max_rpm?: number | null;
    cache?: boolean | null;
    full_output?: boolean;
    default_temperature?: number | null;
    planning?: boolean;
    planning_llm_config?: number | null;
    manager_llm_config?: number | null;
    embedding_config?: number | null;
    memory_llm_config?: number | null;
    metadata?: Record<string, unknown> | null;
    similarity_threshold?: string | null;
    search_limit?: number | null;
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
    config?: Record<string, unknown> | null;
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
