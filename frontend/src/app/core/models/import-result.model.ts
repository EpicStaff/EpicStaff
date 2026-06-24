export interface ImportResultItem {
    id: number | string;
    name: string;
}

export interface FlowImportResultItem extends ImportResultItem {
    description?: string | null;
    time_to_live?: number | null;
    persistent_variables?: boolean | null;
}

export interface ProjectImportResultItem extends ImportResultItem {
    description?: string | null;
    process?: string | null;
    memory?: boolean | null;
    max_rpm?: number | null;
    planning?: boolean | null;
}

export interface AgentImportResultItem extends ImportResultItem {
    goal?: string | null;
    backstory?: string | null;
    max_iter?: number | null;
    memory?: boolean | null;
    allow_delegation?: boolean | null;
    allow_code_execution?: boolean | null;
}

export interface LLMModelImportResultItem extends ImportResultItem {
    provider_name?: string | null;
    predefined?: boolean | null;
    is_custom?: boolean | null;
    description?: string | null;
}

export interface LLMConfigImportResultItem extends ImportResultItem {
    custom_name?: string | null;
    temperature?: number | null;
    max_tokens?: number | null;
    timeout?: number | null;
}

export interface PythonCodeToolImportResultItem extends ImportResultItem {
    description?: string | null;
}

export interface MCPToolImportResultItem extends ImportResultItem {
    description?: string | null;
}

export interface RealtimeModelImportResultItem extends ImportResultItem {
    provider_name?: string | null;
    is_custom?: boolean | null;
}

export interface RealtimeConfigImportResultItem extends ImportResultItem {
    custom_name?: string | null;
}

export interface EntityTypeResult<T extends ImportResultItem = ImportResultItem> {
    total: number;
    created: {
        count: number;
        items: T[];
    };
    reused: {
        count: number;
        items: T[];
    };
}

export interface ImportResult {
    Flow?: EntityTypeResult<FlowImportResultItem>;
    Project?: EntityTypeResult<ProjectImportResultItem>;
    Agent?: EntityTypeResult<AgentImportResultItem>;
    LLMModel?: EntityTypeResult<LLMModelImportResultItem>;
    LLMConfig?: EntityTypeResult<LLMConfigImportResultItem>;
    PythonCodeTool?: EntityTypeResult<PythonCodeToolImportResultItem>;
    MCPTool?: EntityTypeResult<MCPToolImportResultItem>;
    RealtimeModel?: EntityTypeResult<RealtimeModelImportResultItem>;
    RealtimeConfig?: EntityTypeResult<RealtimeConfigImportResultItem>;
    [key: string]: EntityTypeResult | undefined;
}

export interface ImportResultDialogData {
    importResult: ImportResult;
}
