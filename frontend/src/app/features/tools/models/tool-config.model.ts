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
    agent_surface: UsageItem[];
    inline: UsageItem[];
    shared_surface: UsageItem[];
}

export interface UsageItem {
    id: number;
    name: string;
}

export interface GetBulkToolUsageItem {
    id: number;
    agent_surface_count: number;
    inline_count: number;
    is_built_in: boolean;
    shared_surface_count: number;
}

export interface BulkDeleteToolsResponse {
    deleted: number;
    ids: number[];
}
