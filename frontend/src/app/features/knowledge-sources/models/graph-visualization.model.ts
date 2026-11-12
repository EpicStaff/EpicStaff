export interface VisualizationEntity {
    id: string;
    title: string;
    type: string | null;
    degree: number;
    community_ids: string[];
}

export interface VisualizationRelationship {
    id: string;
    source: string;
    target: string;
    weight: number;
}

export interface GraphVisualizationData {
    entities: VisualizationEntity[];
    relationships: VisualizationRelationship[];
    total_entities: number;
    total_relationships: number;
}

export interface GraphTableData {
    columns: string[];
    rows: Record<string, unknown>[];
    total: number;
    page: number;
    page_size: number;
}
