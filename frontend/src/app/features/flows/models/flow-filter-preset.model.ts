export interface FlowFilterPreset {
    id: number;
    name: string;
    filter_body: Record<string, unknown>;
    created_at: string;
    updated_at: string;
}

export interface FlowFilterPresetCreate {
    name: string;
    filter_body: Record<string, unknown>;
}

export interface FlowFilterPresetUpdate {
    name?: string;
    filter_body?: Record<string, unknown>;
}
