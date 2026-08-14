export interface ToolConfig {
    id: number;
    name: string;
    configuration: Record<string, unknown>;
    tool: number;
    is_completed: boolean;
    toolName?: string;
    toolDescription?: string;
}

export interface GetToolUsage {
    projects: ProjectUsageItem[];
    staff: AgentUsageItem[];
}

export interface ProjectUsageItem {
    id: number;
    name: string;
}

export interface AgentUsageItem {
    id: number;
    role: string;
}

export interface GetBulkToolUsageItem {
    id: number;
    projects_count: number;
    staff_count: number;
    is_built_in: boolean;
}

export interface BulkDeleteToolsResponse {
    deleted: number;
    ids: number[];
}
