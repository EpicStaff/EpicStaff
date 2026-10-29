export interface ToolFilterPreset {
    id: number;
    name: string;
    filter_body: Record<string, unknown>;
    created_at: string;
    updated_at: string;
}

export interface ToolFilterPresetCreate {
    name: string;
    filter_body: Record<string, unknown>;
}

export interface ToolFilterPresetUpdate {
    name?: string;
    filter_body?: Record<string, unknown>;
}
