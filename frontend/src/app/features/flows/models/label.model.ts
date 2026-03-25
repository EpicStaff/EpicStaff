export interface LabelDto {
    id: number;
    name: string;
    parent: number | null;
    full_path: string;
    created_at: string;
}

export interface CreateLabelRequest {
    name: string;
    parent?: number | null;
}

export interface UpdateLabelRequest {
    name: string;
    parent?: number | null;
}
